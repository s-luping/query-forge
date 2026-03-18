# -*- coding: UTF-8 -*-
"""
SQL生成流程优化类 - 字段级索引 + 按表聚合
检索阶段：根据用户问题检索top-K个最相关的字段
聚合阶段：收集这些字段所属的表，去重后获取这些表的完整结构
"""
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from app.logger import pipeline_logger
from core.KeywordExtractor import KeywordExtractor
from core.LLMClient import LLMClient
from core.SQLGenerator import SqlGenerator
from models import SchemaSessionLocal
from models.schema import Schema


class SQLPipeline:
    """SQL生成流程优化类 - 字段级索引 + 按表聚合
    
    必要依赖：
        - user_id: 用户ID
        - llm_client: LLM客户端
        - sql_generator: SQL生成器
        
    可选依赖（缺失不影响流程）：
        - vector_store: 向量存储（失败时降级到数据库查询）
        - schema_name: 模式名
        - domain_knowledge: 领域知识
        - sample_values: 字段示例值
        - table_relations: 表间关系
        - history_queries: 历史成功查询
    """

    VECTOR_INDEX_THRESHOLD = 50
    FIELD_RECALL_TOP_K = 20
    MAX_TABLES = 10

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator):
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()
        self._vector_loaded = False
        self._vector_error = None
        self._pipeline_log = []

    def _log_step(self, step_name: str, data: dict, level: str = "INFO"):
        """记录步骤日志"""
        log_entry = {
            "step": step_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
        log_data = {
            "user_id": self.user_id,
            "query": query,
            "schema_name": schema_name or "全部",
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._log_step("PIPELINE_START", log_data)

    def _log_pipeline_end(self, result: dict):
        """记录流程结束"""
        log_data = {
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_valid": result.get("is_valid"),
            "sql_length": len(result.get("sql", "")),
            "used_vector_search": result.get("used_vector_search"),
            "total_tokens": result.get("total_tokens", 0)
        }
        self._log_step("PIPELINE_END", log_data)

    def _get_schemas(self, schema_name: Optional[str] = None) -> List[Dict]:
        """获取schema数据（必要）"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            items = query.all()
            return [{
                'table_name': s.table_name,
                'column_name': s.column_name,
                'column_description': s.column_description,
                'column_type': s.column_type,
                'sample_values': s.sample_values
            } for s in items]
        finally:
            db.close()

    def _get_table_complete_fields(self, table_names: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """获取指定表的完整字段结构（必要）"""
        if not table_names:
            return []

        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(
                Schema.user_id == self.user_id,
                Schema.table_name.in_(table_names)
            )
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()
            return [{
                'table_name': s.table_name,
                'column_name': s.column_name,
                'column_description': s.column_description,
                'column_type': s.column_type,
                'sample_values': s.sample_values
            } for s in items]
        finally:
            db.close()

    def _get_field_count(self, schema_name: Optional[str] = None) -> int:
        """获取字段数量（必要）"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            return query.count()
        finally:
            db.close()

    def _try_load_vector_store(self, schema_name: Optional[str] = None) -> bool:
        """尝试加载向量索引（可选，失败返回False）"""
        try:
            from core.VectorStore import SchemaVectorStore
            
            field_count = self._get_field_count(schema_name)
            
            self._log_step("VECTOR_CHECK", {
                "field_count": field_count,
                "threshold": self.VECTOR_INDEX_THRESHOLD,
                "need_vector": field_count >= self.VECTOR_INDEX_THRESHOLD
            })
            
            if field_count < self.VECTOR_INDEX_THRESHOLD:
                return False

            self.vector_store = SchemaVectorStore(self.user_id)

            if self.vector_store.load(schema_name):
                self._vector_loaded = True
                self._log_step("VECTOR_LOAD", {
                    "status": "loaded",
                    "field_count": self.vector_store.field_index.count
                })
                return True

            schemas = self._get_schemas(schema_name)
            if schemas:
                self.vector_store.build_from_schemas(schemas, schema_name)
                self._vector_loaded = True
                self._log_step("VECTOR_BUILD", {
                    "status": "built",
                    "field_count": len(schemas)
                })
                return True

            return False
        except Exception as e:
            self._vector_error = str(e)
            self._log_step("VECTOR_ERROR", {
                "error": str(e),
                "fallback": "database_query"
            }, level="ERROR")
            return False

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
        if self._vector_loaded:
            try:
                keyword_text = ' '.join(keywords)
                results = self.vector_store.search_fields(keyword_text, top_k=self.FIELD_RECALL_TOP_K)
                if results:
                    self._log_step("STEP2_VECTOR_RECALL", {
                        "method": "vector_search",
                        "keyword_text": keyword_text,
                        "recalled_count": len(results),
                        "recalled_fields": [
                            {"table": f.get("table_name"), "column": f.get("column_name")}
                            for f in results[:10]
                        ]
                    })
                    return results
            except Exception:
                pass

        return self._recall_fields_from_db(keywords, schema_name)

    def _recall_fields_from_db(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """数据库查询召回字段（降级方案）"""
        keyword_set = set(k.lower() for k in keywords)
        schemas = self._get_schemas(schema_name)
        results = []
        for s in schemas:
            table = s['table_name'].lower()
            column = s['column_name'].lower()
            desc = (s['column_description'] or '').lower()
            if any(kw in table or kw in column or kw in desc for kw in keyword_set):
                results.append(s)
        
        self._log_step("STEP2_DB_RECALL", {
            "method": "database_query",
            "keywords": list(keyword_set),
            "total_fields": len(schemas),
            "recalled_count": len(results),
            "recalled_fields": [
                {"table": f.get("table_name"), "column": f.get("column_name")}
                for f in results[:10]
            ]
        })
        
        return results[:self.FIELD_RECALL_TOP_K]

    def step3_aggregate_tables(self, recalled_fields: List[Dict], schema_name: Optional[str] = None) -> Dict:
        """步骤3: 聚合表获取完整结构（必要）"""
        table_names = list(set(f.get('table_name') for f in recalled_fields if f.get('table_name')))

        if len(table_names) > self.MAX_TABLES:
            table_counts = {}
            for f in recalled_fields:
                t = f.get('table_name')
                if t:
                    table_counts[t] = table_counts.get(t, 0) + 1
            table_names = sorted(table_counts.keys(), key=lambda x: table_counts.get(x, 0), reverse=True)[:self.MAX_TABLES]

        complete_fields = self._get_table_complete_fields(table_names, schema_name)

        all_fields = {}
        for f in complete_fields:
            key = f"{f.get('table_name')}.{f.get('column_name')}"
            all_fields[key] = {
                'table_name': f.get('table_name'),
                'column_name': f.get('column_name'),
                'column_type': f.get('column_type'),
                'column_description': f.get('column_description'),
                'sample_values': f.get('sample_values', '')
            }
            if f.get('sample_values'):
                samples = [v.strip() for v in f['sample_values'].split(',') if v.strip()][:5]
                if samples:
                    all_fields[key]['sample_values_list'] = samples

        self._log_step("STEP3_AGGREGATE", {
            "recalled_table_count": len(table_names),
            "tables": table_names,
            "total_field_count": len(all_fields),
            "fields_preview": [
                {
                    "table": f.get("table_name"),
                    "column": f.get("column_name"),
                    "type": f.get("column_type"),
                    "desc": f.get("column_description", "")[:50] if f.get("column_description") else ""
                }
                for f in complete_fields[:15]
            ]
        })

        return {
            'recalled_fields': recalled_fields,
            'tables': table_names,
            'all_fields': all_fields
        }

    def step4_add_context_info(self, merged_info: Dict, query: str,
                               domain_knowledge: str = "", history_queries: List[Dict] = None,
                               sample_values: str = "", table_relations: str = "") -> Dict:
        """步骤4: 添加上下文信息（可选参数不影响流程）"""
        merged_info['context'] = {
            'query': query,
            'domain_knowledge': domain_knowledge or "",
            'history_queries': history_queries or [],
            'sample_values': sample_values or "",
            'table_relations': table_relations or ""
        }
        
        self._log_step("STEP4_CONTEXT", {
            "query": query,
            "has_domain_knowledge": bool(domain_knowledge),
            "domain_knowledge_length": len(domain_knowledge) if domain_knowledge else 0,
            "has_sample_values": bool(sample_values),
            "sample_values_length": len(sample_values) if sample_values else 0,
            "has_table_relations": bool(table_relations),
            "table_relations_length": len(table_relations) if table_relations else 0,
            "history_queries_count": len(history_queries) if history_queries else 0
        })
        
        return merged_info

    def step5_generate_sql(self, merged_info: Dict, db_type: str = "sqlite") -> Dict:
        """步骤5: 生成SQL（必要）"""
        schema_csv = self._generate_schema_csv(merged_info)
        sample_values = self._generate_sample_values(merged_info)

        extra_sample_values = merged_info['context'].get('sample_values', '')
        if extra_sample_values:
            sample_values = f"{sample_values}\n{extra_sample_values}" if sample_values else extra_sample_values

        prompt = self.sql_generator.generate_sql_prompt(
            query=merged_info['context']['query'],
            schema_csv=schema_csv,
            sample_values=sample_values,
            table_relations=merged_info['context'].get('table_relations', ''),
            history_queries=merged_info['context']['history_queries'],
            domain_knowledge=merged_info['context']['domain_knowledge'],
            db_type=db_type
        )

        self._log_step("STEP5_PROMPT", {
            "db_type": db_type,
            "schema_csv_lines": len(schema_csv.split('\n')),
            "sample_values_lines": len(sample_values.split('\n')) if sample_values else 0,
            "prompt_length": len(prompt)
        })

        result = self.llm_client.call_llm_with_details(prompt)
        
        self._log_step("STEP5_RESULT", {
            "sql": result.get("sql", ""),
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
            "total_tokens": result.get("total_tokens", 0)
        })
        
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

    def _generate_schema_csv(self, merged_info: Dict) -> str:
        lines = ["表名,字段名,字段类型,字段描述"]
        tables = merged_info.get('tables', [])
        all_fields = merged_info.get('all_fields', {})

        for table in tables:
            table_fields = [(key, field) for key, field in all_fields.items() if field.get('table_name') == table]
            for key, field in table_fields:
                lines.append(f"{table},{field.get('column_name', '')},"
                           f"{field.get('column_type', '')},{field.get('column_description', '')}")
        return '\n'.join(lines)

    def _generate_sample_values(self, merged_info: Dict) -> str:
        lines = []
        all_fields = merged_info.get('all_fields', {})
        for key, field in all_fields.items():
            samples = field.get('sample_values_list', [])
            if samples:
                lines.append(f"{field.get('table_name')}.{field.get('column_name')}: {', '.join(str(s) for s in samples[:5])}")
        return '\n'.join(lines[:20])

    def run_pipeline(self, query: str, schema_name: Optional[str] = None,
                     domain_knowledge: str = "", history_queries: List[Dict] = None,
                     sample_values: str = "", table_relations: str = "",
                     db_type: str = "sqlite") -> Dict:
        """运行SQL生成流程
        
        Args:
            query: 用户问题（必要）
            schema_name: 模式名（可选）
            domain_knowledge: 领域知识（可选）
            history_queries: 历史成功查询（可选）
            sample_values: 字段示例值（可选）
            table_relations: 表间关系（可选）
            db_type: 数据库类型（默认sqlite）
            
        Returns:
            Dict: 包含sql, is_valid, error_message等字段
        """
        self._log_pipeline_start(query, schema_name)

        self._try_load_vector_store(schema_name)

        keywords = self.step1_extract_keywords(query)
        recalled_fields = self.step2_recall_fields(keywords, schema_name)
        merged_info = self.step3_aggregate_tables(recalled_fields, schema_name)
        merged_info = self.step4_add_context_info(
            merged_info, query, domain_knowledge, history_queries,
            sample_values, table_relations
        )
        llm_result = self.step5_generate_sql(merged_info, db_type)
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.step6_validate_sql(sql)

        result = {
            'query': query,
            'keywords': keywords,
            'sql': sql,
            'is_valid': is_valid,
            'error_message': error_msg,
            'columns': columns,
            'used_vector_search': self._vector_loaded,
            'vector_error': self._vector_error,
            'prompt_tokens': llm_result.get('prompt_tokens', 0),
            'completion_tokens': llm_result.get('completion_tokens', 0),
            'total_tokens': llm_result.get('total_tokens', 0),
            'pipeline_log': self._pipeline_log
        }
        
        self._log_pipeline_end(result)

        return result


def build_vector_index(user_id: int, schema_name: Optional[str] = None) -> Dict:
    """构建向量索引"""
    from core.VectorStore import SchemaVectorStore
    
    store = SchemaVectorStore(user_id)
    db = SchemaSessionLocal()
    try:
        query = db.query(Schema).filter(Schema.user_id == user_id)
        if schema_name:
            query = query.filter(Schema.schema_name == schema_name)
        schemas = query.all()
        if not schemas:
            return {'success': False, 'message': '没有数据'}

        schema_list = [{
            'table_name': s.table_name,
            'column_name': s.column_name,
            'column_description': s.column_description,
            'column_type': s.column_type,
            'sample_values': s.sample_values
        } for s in schemas]

        return store.build_from_schemas(schema_list, schema_name)
    finally:
        db.close()


def get_vector_index_info(user_id: int, schema_name: Optional[str] = None) -> Dict:
    """获取向量索引信息"""
    from core.VectorStore import SchemaVectorStore
    
    store = SchemaVectorStore(user_id)
    store.load(schema_name)
    return store.get_info(schema_name)
