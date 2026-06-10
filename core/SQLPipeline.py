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
from core.VectorStore import get_vector_config
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
        - extra_knowledge: 补充知识
        - history_queries: 历史成功查询
    """

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
            query = db.query(Schema).filter(Schema.id > 0)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            items = query.all()
            return [{
                'table_name': s.table_name,
                'column_name': s.column_name,
                'column_description': s.column_description,
                'column_type': s.column_type,
                'column_key': s.column_key,
                'foreign_key': s.foreign_key
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
                Schema.id > 0,
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
                'column_key': s.column_key,
                'foreign_key': s.foreign_key
            } for s in items]
        finally:
            db.close()

    def _get_field_count(self, schema_name: Optional[str] = None) -> int:
        """获取字段数量（必要）"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.id > 0)
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
                "threshold": get_vector_config('VECTOR_INDEX_THRESHOLD'),
                "need_vector": field_count >= get_vector_config('VECTOR_INDEX_THRESHOLD')
            })
            
            if field_count < get_vector_config('VECTOR_INDEX_THRESHOLD'):
                return False

            self.vector_store = SchemaVectorStore()

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
                results = self.vector_store.search_fields(keyword_text, top_k=get_vector_config('FIELD_RECALL_TOP_K'))
                if results:
                    self._log_step("STEP2_VECTOR_RECALL", {
                        "method": "vector_search",
                        "keyword_text": keyword_text,
                        "recalled_count": len(results),
                        "recalled_fields": [
                            {"table": f.get("table_name"), "column": f.get("field_name")}
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
        
        return results[:get_vector_config('FIELD_RECALL_TOP_K')]

    def step3_aggregate_tables(self, recalled_fields: List[Dict], schema_name: Optional[str] = None) -> Dict:
        """步骤3: 聚合表获取完整结构（必要）"""
        table_names = list(set(f.get('table_name') for f in recalled_fields if f.get('table_name')))

        if len(table_names) > get_vector_config('MAX_TABLES'):
            table_counts = {}
            for f in recalled_fields:
                t = f.get('table_name')
                if t:
                    table_counts[t] = table_counts.get(t, 0) + 1
            table_names = sorted(table_counts.keys(), key=lambda x: table_counts.get(x, 0), reverse=True)[:get_vector_config('MAX_TABLES')]

        complete_fields = self._get_table_complete_fields(table_names, schema_name)

        all_fields = {}
        for f in complete_fields:
            key = f"{f.get('table_name')}.{f.get('column_name')}"
            all_fields[key] = {
                'table_name': f.get('table_name'),
                'column_name': f.get('column_name'),
                'column_type': f.get('column_type'),
                'column_description': f.get('column_description'),
                'column_key': f.get('column_key', ''),
                'foreign_key': f.get('foreign_key', '')
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
                    "desc": f.get("column_description", "")[:50] if f.get("column_description") else "",
                    "column_key": f.get("column_key", ""),
                    "foreign_key": f.get("foreign_key", "")
                }
                for f in complete_fields[:15]
            ]
        })

        return {
            'recalled_fields': recalled_fields,
            'tables': table_names,
            'all_fields': all_fields,
            'schema_name': schema_name
        }

    def step4_add_context_info(self, merged_info: Dict, query: str, extra_knowledge: str = "", history_queries: List[Dict] = None) -> Dict:
        """步骤4: 添加上下文信息（可选参数不影响流程）"""
        merged_info['context'] = {
            'query': query,
            'extra_knowledge': extra_knowledge,
            'history_queries': history_queries or []
        }
        
        self._log_step("STEP4_CONTEXT", {
            "query": query,
            "has_extra_knowledge": bool(extra_knowledge),
            "extra_knowledge_length": len(extra_knowledge) if extra_knowledge else 0,
            "history_queries_count": len(history_queries) if history_queries else 0
        })
        
        return merged_info

    def step5_generate_sql(self, merged_info: Dict, db_type: str = "sqlite") -> Dict:
        """步骤5: 生成SQL（必要）"""
        schema_csv = self._generate_schema_csv(merged_info)
        extra_knowledge = merged_info['context'].get('extra_knowledge', '')

        prompt = self.sql_generator.generate_sql_prompt(
            query=merged_info['context']['query'],
            schema_csv=schema_csv,
            extra_knowledge=extra_knowledge,
            history_queries=merged_info['context'].get('history_queries', []),
            db_type=db_type
        )

        self._log_step("STEP5_PROMPT", {
            "db_type": db_type,
            "schema_csv_lines": len(schema_csv.split('\n')),
            "extra_knowledge_length": len(extra_knowledge) if extra_knowledge else 0,
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

    def _generate_schema_csv(self, merged_info: Dict) -> str:
        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        tables = merged_info.get('tables', [])
        all_fields = merged_info.get('all_fields', {})
        schema_name = merged_info.get('schema_name')

        for table in tables:
            table_fields = [(key, field) for key, field in all_fields.items() if field.get('table_name') == table]
            for key, field in table_fields:
                lines.append(f"{table},{field.get('column_name', '')},"
                           f"{field.get('column_type', '')},"
                           f"{field.get('column_description', '')},"
                           f"{field.get('column_key', '')},"
                           f"{field.get('foreign_key', '')}")

        return '\n'.join(lines)

    def run_pipeline(self, query: str, schema_name: Optional[str] = None,
                     extra_knowledge: str = "",
                     history_queries: List[Dict] = None,
                     db_type: str = "sqlite") -> Dict:
        """运行SQL生成流程
        
        Args:
            query: 用户问题（必要）
            schema_name: 模式名（可选）
            extra_knowledge: 补充知识（字段值样例、表间关系、领域知识）
            history_queries: 历史成功查询
            db_type: 数据库类型（默认sqlite）
            
        Returns:
            Dict: 包含sql, is_valid, error_message等字段
        """
        self._log_pipeline_start(query, schema_name)

        self._try_load_vector_store(schema_name)

        keywords = self.step1_extract_keywords(query)
        recalled_fields = self.step2_recall_fields(keywords, schema_name)
        merged_info = self.step3_aggregate_tables(recalled_fields, schema_name)
        merged_info = self.step4_add_context_info(merged_info, query, extra_knowledge, history_queries)
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


def _set_index_meta(schema_name: str, status: str, field_count: int = 0,
                     table_count: int = 0, file_path: str = '', error_msg: str = ''):
    """写入向量索引元数据到数据库"""
    try:
        from models import AppSessionLocal
        from models.vector_index import VectorIndexMeta
        from datetime import datetime

        db = AppSessionLocal()
        try:
            row = db.query(VectorIndexMeta).filter(
                VectorIndexMeta.schema_name == schema_name
            ).first()
            if row is not None:
                # 构建期间有新数据导入导致 stale，不覆盖为 ready
                current = str(row.status)
                if status == 'ready' and current == 'stale':
                    db.close()
                    return
                row.status = status  # type: ignore[assignment]
                if field_count:
                    row.field_count = field_count  # type: ignore[assignment]
                if table_count:
                    row.table_count = table_count  # type: ignore[assignment]
                if file_path:
                    row.file_path = file_path  # type: ignore[assignment]
                if error_msg:
                    row.error_message = error_msg  # type: ignore[assignment]
                if status == 'ready':
                    row.built_at = datetime.now()  # type: ignore[assignment]
            else:
                db.add(VectorIndexMeta(
                    schema_name=schema_name,
                    status=status,
                    field_count=field_count,
                    table_count=table_count,
                    file_path=file_path,
                    error_message=error_msg,
                    built_at=datetime.now() if status == 'ready' else None
                ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # 元数据写入失败不影响索引构建


def _get_index_meta(schema_name: str) -> Optional[dict]:
    """从数据库读取向量索引元数据"""
    try:
        from models import AppSessionLocal
        from models.vector_index import VectorIndexMeta

        db = AppSessionLocal()
        try:
            row = db.query(VectorIndexMeta).filter(
                VectorIndexMeta.schema_name == schema_name
            ).first()
            if row is not None:
                built = str(row.built_at) if row.built_at is not None else None  # type: ignore[union-attr]
                return {
                    'schema_name': str(row.schema_name),
                    'status': str(row.status),
                    'field_count': int(row.field_count),  # type: ignore[arg-type]
                    'table_count': int(row.table_count),  # type: ignore[arg-type]
                    'dimension': int(row.dimension),  # type: ignore[arg-type]
                    'file_path': str(row.file_path),
                    'error_message': str(row.error_message),
                    'built_at': built
                }
        finally:
            db.close()
    except Exception:
        pass
    return None


def build_vector_index(schema_name: Optional[str] = None) -> Dict:
    """构建向量索引"""
    from core.VectorStore import SchemaVectorStore

    store = SchemaVectorStore()
    db = SchemaSessionLocal()
    try:
        query = db.query(Schema).filter(Schema.id > 0)
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
            'column_key': s.column_key,
            'foreign_key': s.foreign_key
        } for s in schemas]

        # 写入构建中状态
        target_schema = schema_name or 'default'
        _set_index_meta(target_schema, 'building')

        result = store.build_from_schemas(schema_list, schema_name)

        if result.get('success'):
            table_count = len(set(s.get('table_name', '') for s in schema_list))
            file_path = store.field_index._last_save_path or ''
            _set_index_meta(
                target_schema, 'ready',
                field_count=result.get('field_count', len(schema_list)),
                table_count=table_count,
                file_path=file_path
            )

        return result
    except Exception as e:
        target_schema = schema_name or 'default'
        _set_index_meta(target_schema, 'error', error_msg=str(e))
        raise
    finally:
        db.close()


def get_vector_index_info(schema_name: Optional[str] = None) -> Dict:
    """获取向量索引信息（优先读数据库元数据）"""
    from core.VectorStore import SchemaVectorStore

    target = schema_name or 'default'
    meta = _get_index_meta(target)

    if meta and meta['status'] == 'ready':
        return {
            'vector_dir': meta.get('file_path', ''),
            'field_count': meta.get('field_count', 0),
            'should_build_index': meta.get('field_count', 0) >= 50,
            'threshold': 50,
            'indexes': {
                'count': meta.get('field_count', 0),
                'is_built': True,
                'filepath': meta.get('file_path', ''),
                'built_at': meta.get('built_at'),
                'table_count': meta.get('table_count', 0)
            },
            'status': meta['status']
        }

    # 元数据不可用，回退到从磁盘加载检查
    store = SchemaVectorStore()
    store.load(schema_name)
    return store.get_info(schema_name)
