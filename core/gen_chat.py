# -*- coding: UTF-8 -*-
"""
多轮对话 SQL 生成器

第一轮走完整召回流水线（委托 core.retrieval.SchemaRetriever），
后续轮次直接复用对话历史 + 首轮已确定的 schema 上下文。
"""
from typing import Optional

from app.logger import logger, pipeline_logger
from app.timezone import now_beijing
from core.llm_client import LLMClient
from core.gen_sql import SqlGenerator
from core.gen_audit import write_query_audit_log
from core.ret_keywords import KeywordExtractor
from core.ret_retriever import SchemaRetriever


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

    # ---------- 链路日志（与 pipeline 对齐，供审计查看） ----------

    def _log_step(self, steps: list, step_name: str, data: dict):
        steps.append({
            "step": step_name,
            "timestamp": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        })

    # ---------- 消息处理 ----------

    def process_first_message(
        self,
        query: str,
        schema_name: Optional[str] = None,
        db_type: str = "sqlite",
        knowledge_content: str = "",
        scope_schema_id: Optional[int] = None
    ) -> dict:
        """第一轮消息：走完整流水线（关键词→字段召回→表聚合→LLM生成）

        Returns:
            {"sql": ..., "is_valid": ..., "schema_csv": ..., "messages": [...]}
        """
        import json
        start_time = now_beijing()
        pipeline_log = []
        self._log_step(pipeline_log, "PIPELINE_START", {
            "user_id": self.user_id, "query": query,
            "schema_name": schema_name or "全部",
        })

        # Step 1: 关键词提取
        keywords = self.keyword_extractor.extract(query, top_k=10)
        self._log_step(pipeline_log, "STEP1_KEYWORDS", {
            "query": query, "keywords": keywords, "count": len(keywords)})

        # Step 2: 字段召回（向量优先，DB 降级）
        recalled_fields = self.retriever.recall_fields(keywords, schema_name)
        self._log_step(pipeline_log, "STEP2_RECALL", {
            "method": "vector" if self.retriever.vector_loaded else "database_query",
            "keywords": keywords, "recalled_count": len(recalled_fields),
            "recalled_fields": [{"table": f.get("table_name"), "column": f.get("column_name")}
                                for f in recalled_fields[:10]]})

        # Step 3: 按表聚合，获取完整表结构
        aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
        self._log_step(pipeline_log, "STEP3_AGGREGATE", {
            "recalled_table_count": len(aggregation.get('tables', [])),
            "tables": aggregation.get('tables', []),
            "total_field_count": len(aggregation.get('all_fields', {}))})

        # 概念级召回：typed 知识单独召回 + relation 动态扩表
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        recall = self.retriever.recall_knowledge(query, scope_schema_id=scope_id)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "matched_count": len(recall['items']),
            "related_tables": recall['related_tables']})
        if recall['related_tables']:
            aggregation = self.retriever.extend_aggregation_with_tables(
                aggregation, recall['related_tables'], schema_name)
            self._log_step(pipeline_log, "STEP_EXTEND_TABLES", {
                "tables": aggregation.get('tables', []),
                "total_field_count": len(aggregation.get('all_fields', {}))})

        # 构建 schema CSV（会保存到对话上下文，供后续轮次复用）
        schema_csv = SchemaRetriever.build_schema_csv(aggregation)

        logger.info(f"[ChatSession] 第一轮 - schema 上下文已构建，字段数: {len(aggregation.get('all_fields', {}))}")

        # Step 4: 构建 messages 数组（召回的知识文本并入【领域知识】）
        kb = knowledge_content or ""
        if recall['prompt_text']:
            kb = (kb + "\n\n" + recall['prompt_text']).strip() if kb else recall['prompt_text']
        system_prompt = self._build_system_prompt(schema_csv, db_type, kb)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        self._log_step(pipeline_log, "STEP4_CONTEXT", {
            "has_knowledge": bool(knowledge_content),
            "schema_csv_lines": len(schema_csv.split('\n'))})

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)
        self._log_step(pipeline_log, "STEP5_RESULT", {
            "sql": llm_result.get('sql', ''),
            "total_tokens": llm_result.get("total_tokens", 0)})

        # Step 6-7: 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        generated_sql = sql
        sql, is_valid, error_msg, gateway_info = self._apply_gateway(
            sql, is_valid, error_msg, db_type, schema_name)
        self._log_step(pipeline_log, "STEP6_VALIDATE", {
            "is_valid": is_valid, "error_message": error_msg,
            "columns": columns[:10] if columns else None})
        if gateway_info:
            self._log_step(pipeline_log, "STEP7_GATEWAY", {
                "is_allowed": gateway_info.get("is_allowed"),
                "block_reason": gateway_info.get("block_reason"),
                "was_modified": gateway_info.get("was_modified"),
                "tables": gateway_info.get("tables", []),
                "hit_sensitive": gateway_info.get("hit_sensitive", False)})

        # Step 8: 审计日志
        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
        write_query_audit_log(
            self.user_id, self.user, query, generated_sql, sql,
            gateway_result=gateway_info, duration_ms=duration_ms,
            pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str)
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
            "pipeline_log": pipeline_log,
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
        schema_name: Optional[str] = None,
        knowledge_content: str = "",
        scope_schema_id: Optional[int] = None
    ) -> dict:
        """后续轮次消息：使用对话历史 + 已保存的 schema 上下文

        Args:
            conversation_messages: 数据库中已存储的消息（含 role/content/sql）
            new_user_content: 用户的新消息（修改意见）
            schema_csv: 第一轮保存的 schema CSV
            db_type: 数据库类型
            schema_name: 数据源/schema 名（用于追问召回追踪）
            knowledge_content: 创建对话时关联的知识库内容

        Returns:
            {"sql": ..., "is_valid": ..., "messages": [...]}
        """
        import json
        start_time = now_beijing()
        pipeline_log = []
        self._log_step(pipeline_log, "PIPELINE_START", {
            "user_id": self.user_id, "query": new_user_content,
            "schema_name": schema_name or "复用上一轮", "mode": "followup",
        })

        # Step 1: 关键词提取（对追问重新提取，保证链路完整）
        keywords = self.keyword_extractor.extract(new_user_content, top_k=10)
        self._log_step(pipeline_log, "STEP1_KEYWORDS", {
            "query": new_user_content, "keywords": keywords,
            "count": len(keywords), "mode": "followup"})

        # Step 2-3: 针对新问题重新召回/聚合（仅链路追踪；失败降级不阻断主流程）
        try:
            recalled_fields = self.retriever.recall_fields(keywords, schema_name)
            self._log_step(pipeline_log, "STEP2_RECALL", {
                "method": "vector" if self.retriever.vector_loaded else "database_query",
                "keywords": keywords, "recalled_count": len(recalled_fields),
                "recalled_fields": [{"table": f.get("table_name"), "column": f.get("column_name")}
                                    for f in recalled_fields[:10]]})
            aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
            self._log_step(pipeline_log, "STEP3_AGGREGATE", {
                "recalled_table_count": len(aggregation.get('tables', [])),
                "tables": aggregation.get('tables', []),
                "total_field_count": len(aggregation.get('all_fields', {}))})
        except Exception as e:
            logger.warning(f"[ChatSession] 追问召回失败，降级复用上一轮上下文: {e}")
            self._log_step(pipeline_log, "STEP2_RECALL", {
                "method": "reuse_previous_context", "keywords": keywords,
                "recalled_count": 0, "recalled_fields": []})
            self._log_step(pipeline_log, "STEP3_AGGREGATE", {
                "reuse_schema_csv": True,
                "schema_csv_lines": len(schema_csv.split('\n'))})

        messages = self._build_messages_from_history(
            conversation_messages, schema_csv, db_type, knowledge_content
        )

        # 概念级召回：追问也单独召回 typed 知识，文本并入【领域知识】
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        followup_recall = self.retriever.recall_knowledge(new_user_content, scope_schema_id=scope_id)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "matched_count": len(followup_recall['items']),
            "related_tables": followup_recall['related_tables']})
        if followup_recall['prompt_text']:
            # 在现有 system prompt 末尾追加召回知识（复用已构建的 messages）
            if messages and messages[0].get('role') == 'system':
                extra = followup_recall['prompt_text']
                base = messages[0]['content']
                if extra not in base:
                    messages[0]['content'] = (base + "\n\n【领域知识(追问召回)】\n" + extra).strip()

        # 追加新的 user 消息
        messages.append({"role": "user", "content": new_user_content})

        logger.info(f"[ChatSession] 跟进消息 - 历史轮次: {len(conversation_messages)}，总消息: {len(messages)}")

        # Step 4: 上下文
        self._log_step(pipeline_log, "STEP4_CONTEXT", {
            "has_knowledge": bool(knowledge_content),
            "history_rounds": len(conversation_messages),
            "schema_csv_lines": len(schema_csv.split('\n'))})

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)
        self._log_step(pipeline_log, "STEP5_RESULT", {
            "sql": llm_result.get('sql', ''),
            "total_tokens": llm_result.get("total_tokens", 0)})

        # Step 6-7: 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        generated_sql = sql
        sql, is_valid, error_msg, gateway_info = self._apply_gateway(
            sql, is_valid, error_msg, db_type, schema_name)
        self._log_step(pipeline_log, "STEP6_VALIDATE", {
            "is_valid": is_valid, "error_message": error_msg,
            "columns": columns[:10] if columns else None})
        if gateway_info:
            self._log_step(pipeline_log, "STEP7_GATEWAY", {
                "is_allowed": gateway_info.get("is_allowed"),
                "block_reason": gateway_info.get("block_reason"),
                "was_modified": gateway_info.get("was_modified"),
                "tables": gateway_info.get("tables", []),
                "hit_sensitive": gateway_info.get("hit_sensitive", False)})

        # Step 8: 审计日志（与首轮一致：完整链路 问题→关键词→召回→生成）
        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
        try:
            write_query_audit_log(
                self.user_id, self.user, new_user_content, generated_sql, sql,
                gateway_result=gateway_info, duration_ms=duration_ms,
                pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str))
        except Exception:
            logger.warning("跟进消息审计日志写入失败（不影响主流程）")

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "messages": messages,
            "duration_ms": duration_ms,
            "raw_response": llm_result.get("raw_response", ""),
            "gateway": gateway_info,
            "pipeline_log": pipeline_log,
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
            from services.sql_gateway import SqlGateway
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
            # 兼容 dict（router 传入）与 ORM 对象两种形态
            role = msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', None)
            content = msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', '')
            sql = msg.get('sql') if isinstance(msg, dict) else getattr(msg, 'sql', None)
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                # 助理消息使用提取的 SQL 作为 content
                assistant_content = sql or content
                messages.append({"role": "assistant", "content": assistant_content})

        return messages
