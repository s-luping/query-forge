# -*- coding: UTF-8 -*-
"""
多轮对话 SQL 生成器

第一轮走完整召回流水线（委托 core.retrieval.SchemaRetriever），
后续轮次直接复用对话历史 + 首轮已确定的 schema 上下文。
"""
from typing import Optional

from app.logger import logger
from core.llm.client import LLMClient
from core.generation.sql_generator import SqlGenerator
from core.generation.audit import write_query_audit_log
from core.retrieval.keywords import KeywordExtractor
from core.retrieval.retriever import SchemaRetriever


class ChatSession:
    """对话 SQL 生成器"""

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator,
                 user: dict = None):
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()
        self.retriever = SchemaRetriever(user=user, user_id=user_id)
        self.user = user or {'user_id': user_id, 'role': 'user'}

    # ---------- 消息处理 ----------

    def process_first_message(
        self,
        query: str,
        schema_name: Optional[str] = None,
        db_type: str = "sqlite",
        knowledge_content: str = ""
    ) -> dict:
        """第一轮消息：走完整流水线（关键词→字段召回→表聚合→LLM生成）

        Returns:
            {"sql": ..., "is_valid": ..., "schema_csv": ..., "messages": [...]}
        """
        from datetime import datetime
        start_time = datetime.now()

        # Step 1: 关键词提取
        keywords = self.keyword_extractor.extract(query, top_k=10)

        # Step 2: 字段召回（向量优先，DB 降级）
        recalled_fields = self.retriever.recall_fields(keywords, schema_name)

        # Step 3: 按表聚合，获取完整表结构
        aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)

        # 构建 schema CSV（会保存到对话上下文，供后续轮次复用）
        schema_csv = SchemaRetriever.build_schema_csv(aggregation)

        logger.info(f"[ChatSession] 第一轮 - schema 上下文已构建，字段数: {len(aggregation.get('all_fields', {}))}")

        # Step 4: 构建 messages 数组
        system_prompt = self._build_system_prompt(schema_csv, db_type, knowledge_content)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)

        # Step 6-7: 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        generated_sql = sql
        sql, is_valid, error_msg, gateway_info = self._apply_gateway(
            sql, is_valid, error_msg, db_type, schema_name)

        # Step 8: 审计日志
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        write_query_audit_log(
            self.user_id, self.user, query, generated_sql, sql,
            gateway_result=gateway_info, duration_ms=duration_ms
        )

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "schema_csv": schema_csv,
            "keywords": keywords,
            "messages": messages,
            "duration_ms": duration_ms,
            "raw_response": llm_result.get("raw_response", ""),
            "gateway": gateway_info,
            "tokens": {
                "prompt_tokens": llm_result.get("prompt_tokens", 0),
                "completion_tokens": llm_result.get("completion_tokens", 0),
                "total_tokens": llm_result.get("total_tokens", 0)
            }
        }

    def process_followup_message(
        self,
        conversation_messages: list,
        new_user_content: str,
        schema_csv: str,
        db_type: str = "sqlite",
        knowledge_content: str = ""
    ) -> dict:
        """后续轮次消息：使用对话历史 + 已保存的 schema 上下文

        Args:
            conversation_messages: 数据库中已存储的消息（含 role/content/sql）
            new_user_content: 用户的新消息（修改意见）
            schema_csv: 第一轮保存的 schema CSV
            db_type: 数据库类型
            knowledge_content: 创建对话时关联的知识库内容

        Returns:
            {"sql": ..., "is_valid": ..., "messages": [...]}
        """
        messages = self._build_messages_from_history(
            conversation_messages, schema_csv, db_type, knowledge_content
        )

        # 追加新的 user 消息
        messages.append({"role": "user", "content": new_user_content})

        logger.info(f"[ChatSession] 跟进消息 - 历史轮次: {len(conversation_messages)}，总消息: {len(messages)}")

        # 调用 LLM
        llm_result = self.llm_client.chat(messages)

        # 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        sql, is_valid, error_msg, _ = self._apply_gateway(
            sql, is_valid, error_msg, db_type)

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "messages": messages,
            "duration_ms": llm_result.get("duration_ms", 0),
            "raw_response": llm_result.get("raw_response", ""),
            "tokens": {
                "prompt_tokens": llm_result.get("prompt_tokens", 0),
                "completion_tokens": llm_result.get("completion_tokens", 0),
                "total_tokens": llm_result.get("total_tokens", 0)
            }
        }

    # ---------- 内部方法 ----------

    def _apply_gateway(self, sql: str, is_valid: bool, error_msg: Optional[str],
                       db_type: str, schema_name: Optional[str] = None):
        """SQL 权限网关：拦截 / 改写；失败不阻断主流程

        Returns:
            (sql, is_valid, error_msg, gateway_info)
        """
        if not is_valid:
            return sql, is_valid, error_msg, None
        try:
            from services.sql.gateway import SqlGateway
            gw = SqlGateway(self.user)
            gw_result = gw.process(sql, schema_name=schema_name, db_type=db_type)
            if not gw_result.is_allowed:
                is_valid = False
                error_msg = gw_result.block_reason
            elif gw_result.was_modified:
                sql = gw_result.sql
            return sql, is_valid, error_msg, gw_result.to_dict()
        except Exception as e:
            logger.warning(f"[ChatSession] 网关处理失败: {e}")
            return sql, is_valid, error_msg, None

    def _build_system_prompt(self, schema_csv: str, db_type: str, knowledge_content: str = "") -> str:
        """构建 system prompt"""
        db_name = db_type.upper() if db_type else "SQLite"
        prompt = f"""你是一个专业的SQL生成助手。请根据用户的自然语言查询和表结构，生成正确的{db_name}查询语句。

【表结构】
{schema_csv}

【规则】
1. 只生成SELECT查询语句，不要包含INSERT、UPDATE、DELETE等操作
2. 确保所有列名和表名都在提供的表结构中存在
3. 如果需要连接多个表，请使用适当的JOIN
4. 添加适当的WHERE条件来过滤数据
5. 如果用户提出修改意见，请基于上一轮的SQL进行修改优化
6. 维度层级过滤（极其重要）：数据采用父子层级存储，父节点值=子节点汇总（预聚合）。【领域知识】中列出的每一个维度列都必须添加 WHERE 条件，用户未指定时使用最高级父节点（根节点），不要混用不同层级。遗漏任何一个维度列都会导致数据翻倍"""

        if knowledge_content:
            prompt += f"\n\n【领域知识】\n{knowledge_content}"

        prompt += "\n\n只返回SQL语句，不要包含其他解释文字。"
        return prompt

    def _build_messages_from_history(
        self,
        conversation_messages: list,
        schema_csv: str,
        db_type: str = "sqlite",
        knowledge_content: str = ""
    ) -> list:
        """将数据库消息历史转换为 LLM messages 数组"""
        messages = [
            {"role": "system", "content": self._build_system_prompt(schema_csv, db_type, knowledge_content)}
        ]

        for msg in conversation_messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                # 助理消息使用提取的 SQL 作为 content
                assistant_content = msg.sql or msg.content
                messages.append({"role": "assistant", "content": assistant_content})

        return messages
