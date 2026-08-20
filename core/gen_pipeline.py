# -*- coding: UTF-8 -*-
"""
单轮 SQL 生成流水线 — 字段级索引 + 按表聚合

步骤编排（检索/聚合委托 core.retrieval.retriever.SchemaRetriever）：
  step1 关键词 → step2 字段召回 → step3 表聚合 → step4 上下文
  → step5 LLM 生成 → step6 校验 → step7 权限网关 → step8 审计
"""
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from app.logger import pipeline_logger
from app.timezone import now_beijing
from core.llm_client import LLMClient
from core.gen_sql import SqlGenerator
from core.gen_audit import write_query_audit_log
from core.ret_keywords import KeywordExtractor
from core.ret_retriever import SchemaRetriever
from core.ret_vector_store import get_vector_config


class SQLPipeline:
    """SQL生成流程优化类 - 字段级索引 + 按表聚合

    必要依赖：
        - user_id: 用户ID
        - llm_client: LLM客户端
        - sql_generator: SQL生成器

    可选依赖（缺失不影响流程）：
        - schema_name: 模式名
        - knowledge_content: 知识库内容（业务口径/表关系/计算规则）
        - history_queries: 历史成功查询
    """

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator,
                 user: dict = None):
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()
        self.retriever = SchemaRetriever(user=user, user_id=user_id)
        self._pipeline_log = []
        self.user = user or {'user_id': user_id, 'role': 'user'}

    # ---------- 流程日志 ----------

    def _log_step(self, step_name: str, data: dict, level: str = "INFO"):
        """记录步骤日志"""
        log_entry = {
            "step": step_name,
            "timestamp": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data
        }
        self._pipeline_log.append(log_entry)

        log_message = f"[{step_name}]\n{json.dumps(data, ensure_ascii=False, indent=2)}"

        if level == "ERROR":
            pipeline_logger.error(log_message)
        else:
            pipeline_logger.info(log_message)

    def _log_pipeline_start(self, query: str, schema_name: str = None):
        """记录流程开始"""
        self._pipeline_log = []
        self._log_step("PIPELINE_START", {
            "user_id": self.user_id,
            "query": query,
            "schema_name": schema_name or "全部",
            "start_time": now_beijing().strftime("%Y-%m-%d %H:%M:%S")
        })

    def _log_pipeline_end(self, result: dict):
        """记录流程结束"""
        self._log_step("PIPELINE_END", {
            "end_time": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
            "is_valid": result.get("is_valid"),
            "sql_length": len(result.get("sql", "")),
            "used_vector_search": result.get("used_vector_search"),
            "total_tokens": result.get("total_tokens", 0)
        })

    # ---------- 步骤 ----------

    def step1_extract_keywords(self, query: str) -> List[str]:
        """步骤1: 提取关键词（必要）"""
        keywords = self.keyword_extractor.extract(query, top_k=10)

        self._log_step("STEP1_KEYWORDS", {
            "query": query,
            "keywords": keywords,
            "count": len(keywords)
        })

        return keywords

    def step2_recall_fields(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """步骤2: 检索相关字段（必要，向量失败时降级到数据库查询）"""
        results = self.retriever.search_vector(keywords)
        if results:
            self._log_step("STEP2_VECTOR_RECALL", {
                "method": "vector_search",
                "keyword_text": ' '.join(keywords),
                "recalled_count": len(results),
                "recalled_fields": [
                    {"table": f.get("table_name"), "column": f.get("field_name") or f.get("column_name")}
                    for f in results[:10]
                ]
            })
            return results

        results = self.retriever.recall_from_db(keywords, schema_name)
        self._log_step("STEP2_DB_RECALL", {
            "method": "database_query",
            "keywords": keywords,
            "recalled_count": len(results),
            "recalled_fields": [
                {"table": f.get("table_name"), "column": f.get("column_name")}
                for f in results[:10]
            ]
        })
        return results

    def step3_aggregate_tables(self, recalled_fields: List[Dict], schema_name: Optional[str] = None) -> Dict:
        """步骤3: 聚合表获取完整结构（必要）"""
        aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
        all_fields = aggregation['all_fields']

        self._log_step("STEP3_AGGREGATE", {
            "recalled_table_count": len(aggregation['tables']),
            "tables": aggregation['tables'],
            "total_field_count": len(all_fields),
            "fields_preview": [
                {
                    "table": f.get("table_name"),
                    "column": f.get("column_name"),
                    "type": f.get("column_type"),
                    "desc": (f.get("column_description") or "")[:50],
                    "column_key": f.get("column_key", ""),
                    "foreign_key": f.get("foreign_key", "")
                }
                for f in list(all_fields.values())[:15]
            ]
        })

        aggregation['recalled_fields'] = recalled_fields
        return aggregation

    def step4_add_context_info(self, merged_info: Dict, query: str, knowledge_content: str = "", history_queries: List[Dict] = None) -> Dict:
        """步骤4: 添加上下文信息（可选参数不影响流程）"""
        merged_info['context'] = {
            'query': query,
            'knowledge_content': knowledge_content,
            'history_queries': history_queries or []
        }

        self._log_step("STEP4_CONTEXT", {
            "query": query,
            "has_knowledge": bool(knowledge_content),
            "knowledge_length": len(knowledge_content) if knowledge_content else 0,
            "history_queries_count": len(history_queries) if history_queries else 0
        })

        return merged_info

    def step5_generate_sql(self, merged_info: Dict, db_type: str = "sqlite") -> Dict:
        """步骤5: 生成SQL（必要）"""
        schema_csv = SchemaRetriever.build_schema_csv(merged_info)
        knowledge_content = merged_info['context'].get('knowledge_content', '')

        prompt = self.sql_generator.generate_sql_prompt(
            query=merged_info['context']['query'],
            schema_csv=schema_csv,
            knowledge_content=knowledge_content,
            history_queries=merged_info['context'].get('history_queries', []),
            db_type=db_type
        )

        self._log_step("STEP5_PROMPT", {
            "db_type": db_type,
            "schema_csv_lines": len(schema_csv.split('\n')),
            "knowledge_length": len(knowledge_content) if knowledge_content else 0,
            "prompt_length": len(prompt)
        })

        result = self.llm_client.call_llm_with_details(prompt)

        self._log_step("STEP5_RESULT", {
            "sql": result.get("sql", ""),
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
            "total_tokens": result.get("total_tokens", 0)
        })

        result['prompt'] = prompt
        return result

    def step6_validate_sql(self, sql: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
        """步骤6: 验证SQL（必要）"""
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)

        self._log_step("STEP6_VALIDATE", {
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns[:10] if columns else None,
            "columns_count": len(columns) if columns else 0
        })

        return is_valid, error_msg, columns

    # ---------- 主流程 ----------

    def run_pipeline(self, query: str, schema_name: Optional[str] = None,
                     knowledge_content: str = "",
                     history_queries: List[Dict] = None,
                     db_type: str = "sqlite") -> Dict:
        """运行SQL生成流程

        Args:
            query: 用户问题（必要）
            schema_name: 模式名（可选）
            knowledge_content: 知识库内容（业务口径/表关系/计算规则等）
            history_queries: 历史成功查询
            db_type: 数据库类型（默认sqlite）

        Returns:
            Dict: 包含sql, is_valid, error_message等字段
        """
        start_time = now_beijing()
        self._log_pipeline_start(query, schema_name)

        # 向量索引加载（失败自动降级 DB 查询）
        field_count = self.retriever.field_count(schema_name)
        if self.retriever.try_load_vector_store(schema_name):
            self._log_step("VECTOR_LOAD", {
                "status": "loaded",
                "field_count": self.retriever.vector_store.field_index.count
            })
        else:
            self._log_step("VECTOR_CHECK", {
                "field_count": field_count,
                "threshold": get_vector_config('VECTOR_INDEX_THRESHOLD'),
                "need_vector": field_count >= get_vector_config('VECTOR_INDEX_THRESHOLD'),
                "vector_error": self.retriever.vector_error,
                "fallback": "database_query"
            }, level="WARNING" if self.retriever.vector_error else "INFO")

        keywords = self.step1_extract_keywords(query)
        recalled_fields = self.step2_recall_fields(keywords, schema_name)
        merged_info = self.step3_aggregate_tables(recalled_fields, schema_name)
        merged_info = self.step4_add_context_info(merged_info, query, knowledge_content, history_queries)
        llm_result = self.step5_generate_sql(merged_info, db_type)
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.step6_validate_sql(sql)

        # 保存 LLM 原始生成的 SQL（审计用）
        generated_sql = sql

        # Step 7: SQL 权限网关
        gateway_result = None
        if is_valid:
            try:
                from services.sql_gateway import SqlGateway
                gateway = SqlGateway(self.user)
                gateway_result = gateway.process(sql, schema_name=schema_name, db_type=db_type)

                self._log_step("STEP7_GATEWAY", {
                    "is_allowed": gateway_result.is_allowed,
                    "block_reason": gateway_result.block_reason,
                    "was_modified": gateway_result.was_modified,
                    "modifications": gateway_result.modifications,
                    "tables": gateway_result.tables,
                    "hit_sensitive": gateway_result.hit_sensitive,
                })

                if not gateway_result.is_allowed:
                    is_valid = False
                    error_msg = gateway_result.block_reason
                elif gateway_result.was_modified:
                    sql = gateway_result.sql
            except Exception as e:
                self._log_step("STEP7_GATEWAY_ERROR", {"error": str(e)}, level="ERROR")

        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)

        # Step 8: 审计日志
        write_query_audit_log(
            self.user_id, self.user, query, generated_sql, sql,
            gateway_result=gateway_result, duration_ms=duration_ms,
            pipeline_log=json.dumps(self._pipeline_log, ensure_ascii=False, default=str)
        )

        result = {
            'query': query,
            'keywords': keywords,
            'sql': sql,
            'is_valid': is_valid,
            'error_message': error_msg,
            'columns': columns,
            'used_vector_search': self.retriever.vector_loaded,
            'vector_error': self.retriever.vector_error,
            'prompt_tokens': llm_result.get('prompt_tokens', 0),
            'completion_tokens': llm_result.get('completion_tokens', 0),
            'total_tokens': llm_result.get('total_tokens', 0),
            'pipeline_log': self._pipeline_log,
            'gateway': gateway_result.to_dict() if gateway_result else None,
            'duration_ms': duration_ms,
        }

        self._log_pipeline_end(result)

        return result
