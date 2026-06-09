# -*- coding: UTF-8 -*-
"""
对话 SQL 生成器 — 支持多轮连续对话
第一轮走完整流水线，后续轮次直接使用对话历史 + 已确定的 schema 上下文
"""
from typing import List, Dict, Optional

from app.logger import logger
from core.KeywordExtractor import KeywordExtractor
from core.LLMClient import LLMClient
from core.SQLGenerator import SqlGenerator


class ChatSession:
    """对话 SQL 生成器"""

    FIELD_RECALL_TOP_K = 20
    MAX_TABLES = 10

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator):
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()

    def process_first_message(
        self,
        query: str,
        schema_name: Optional[str] = None,
        db_type: str = "sqlite",
        extra_knowledge: str = ""
    ) -> dict:
        """第一轮消息：走完整流水线（关键词→向量检索→表聚合→LLM生成）

        Returns:
            {"sql": ..., "is_valid": ..., "schema_csv": ..., "messages": [...]}
        """
        # Step 1: 关键词提取
        keywords = self.keyword_extractor.extract(query, top_k=10)

        # Step 2: 字段召回
        recalled_fields = self._recall_fields(keywords, schema_name)

        # Step 3: 按表聚合，获取完整表结构
        aggregation = self._aggregate_tables(recalled_fields, schema_name)

        # 构建 schema CSV（会保存到对话上下文，供后续轮次复用）
        schema_csv = self._build_schema_csv(aggregation)

        logger.info(f"[ChatSession] 第一轮 - schema 上下文已构建，字段数: {len(aggregation.get('all_fields', {}))}")

        # Step 4: 构建 messages 数组
        system_prompt = self._build_system_prompt(schema_csv, db_type, extra_knowledge)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)

        # Step 6: 验证 SQL
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "schema_csv": schema_csv,
            "keywords": keywords,
            "messages": messages,
            "duration_ms": llm_result.get("duration_ms", 0),
            "raw_response": llm_result.get("raw_response", ""),
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
        db_type: str = "sqlite"
    ) -> dict:
        """后续轮次消息：使用对话历史 + 已保存的 schema 上下文

        Args:
            conversation_messages: 数据库中已存储的消息（含 role/content/sql）
            new_user_content: 用户的新消息（修改意见）
            schema_csv: 第一轮保存的 schema CSV
            db_type: 数据库类型

        Returns:
            {"sql": ..., "is_valid": ..., "messages": [...]}
        """
        messages = self._build_messages_from_history(
            conversation_messages, schema_csv, db_type
        )

        # 追加新的 user 消息
        messages.append({"role": "user", "content": new_user_content})

        logger.info(f"[ChatSession] 跟进消息 - 历史轮次: {len(conversation_messages)}，总消息: {len(messages)}")

        # 调用 LLM
        llm_result = self.llm_client.chat(messages)

        # 验证 SQL
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)

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

    def _recall_fields(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """字段召回：优先向量检索，失败时降级到数据库查询"""
        from models import SchemaSessionLocal
        from models.schema import Schema

        # 尝试向量检索
        try:
            from core.VectorStore import SchemaVectorStore
            from core.SQLPipeline import build_vector_index, get_vector_index_info

            info = get_vector_index_info(self.user_id, schema_name)
            if info.get('fields', {}).get('is_built'):
                store = SchemaVectorStore(self.user_id)
                store.load(schema_name)
                keyword_text = ' '.join(keywords)
                results = store.search_fields(keyword_text, top_k=self.FIELD_RECALL_TOP_K)
                if results:
                    return results
        except Exception:
            pass

        # 降级到数据库查询
        return self._recall_fields_from_db(keywords, schema_name)

    def _recall_fields_from_db(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """数据库查询召回字段（降级方案）"""
        from models import SchemaSessionLocal
        from models.schema import Schema

        keyword_set = set(k.lower() for k in keywords)
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            schemas = query.all()

            results = []
            for s in schemas:
                table = s.table_name.lower()
                column = s.column_name.lower()
                desc = (s.column_description or '').lower()
                if any(kw in table or kw in column or kw in desc for kw in keyword_set):
                    results.append({
                        'table_name': s.table_name,
                        'column_name': s.column_name,
                        'column_description': s.column_description,
                        'column_type': s.column_type,
                        'column_key': s.column_key,
                        'foreign_key': s.foreign_key
                    })
            return results[:self.FIELD_RECALL_TOP_K]
        finally:
            db.close()

    def _aggregate_tables(self, recalled_fields: List[Dict], schema_name: Optional[str] = None) -> Dict:
        """聚合表：从召回字段中提取表名，获取完整表结构"""
        from models import SchemaSessionLocal
        from models.schema import Schema

        table_names = list(set(f.get('table_name') for f in recalled_fields if f.get('table_name')))

        # 限制最大表数
        if len(table_names) > self.MAX_TABLES:
            table_counts = {}
            for f in recalled_fields:
                t = f.get('table_name')
                if t:
                    table_counts[t] = table_counts.get(t, 0) + 1
            table_names = sorted(table_counts.keys(), key=lambda x: table_counts.get(x, 0), reverse=True)[:self.MAX_TABLES]

        if not table_names:
            # 没有召回任何表，尝试获取全部
            db = SchemaSessionLocal()
            try:
                query = db.query(Schema).filter(Schema.user_id == self.user_id)
                if schema_name:
                    query = query.filter(Schema.schema_name == schema_name)
                all_items = query.all()
                table_names = list(set(s.table_name for s in all_items))[:self.MAX_TABLES]
            finally:
                db.close()

        # 获取这些表的完整字段
        all_fields = {}
        if table_names:
            db = SchemaSessionLocal()
            try:
                query = db.query(Schema).filter(
                    Schema.user_id == self.user_id,
                    Schema.table_name.in_(table_names)
                )
                if schema_name:
                    query = query.filter(Schema.schema_name == schema_name)
                items = query.all()

                for s in items:
                    key = f"{s.table_name}.{s.column_name}"
                    all_fields[key] = {
                        'table_name': s.table_name,
                        'column_name': s.column_name,
                        'column_type': s.column_type or '',
                        'column_description': s.column_description or '',
                        'column_key': s.column_key or '',
                        'foreign_key': s.foreign_key or ''
                    }
            finally:
                db.close()

        return {
            'tables': table_names,
            'all_fields': all_fields,
            'schema_name': schema_name
        }

    def _build_schema_csv(self, aggregation: Dict) -> str:
        """将聚合结果转换为 CSV 格式的 schema 字符串"""
        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        tables = aggregation.get('tables', [])
        all_fields = aggregation.get('all_fields', {})

        for table in tables:
            table_fields = [(key, field) for key, field in all_fields.items()
                            if field.get('table_name') == table]
            for key, field in table_fields:
                lines.append(
                    f"{table},{field.get('column_name', '')},"
                    f"{field.get('column_type', '')},"
                    f"{field.get('column_description', '')},"
                    f"{field.get('column_key', '')},"
                    f"{field.get('foreign_key', '')}"
                )

        return '\n'.join(lines)

    def _build_system_prompt(self, schema_csv: str, db_type: str, extra_knowledge: str = "") -> str:
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
5. 如果用户提出修改意见，请基于上一轮的SQL进行修改优化"""

        if extra_knowledge:
            prompt += f"\n\n【补充知识】\n{extra_knowledge}"

        prompt += "\n\n只返回SQL语句，不要包含其他解释文字。"
        return prompt

    def _build_messages_from_history(
        self,
        conversation_messages: list,
        schema_csv: str,
        db_type: str = "sqlite"
    ) -> list:
        """将数据库消息历史转换为 LLM messages 数组"""
        messages = [
            {"role": "system", "content": self._build_system_prompt(schema_csv, db_type)}
        ]

        for msg in conversation_messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                # 助理消息使用提取的 SQL 作为 content
                assistant_content = msg.sql or msg.content
                messages.append({"role": "assistant", "content": assistant_content})

        return messages
