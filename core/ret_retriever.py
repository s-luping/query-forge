# -*- coding: UTF-8 -*-
"""
共享 Schema 检索器 — 单轮流水线（generation/pipeline.py）与
多轮对话（generation/chat.py）共用的召回层

职责（原 SQLPipeline 与 ChatSession 中三份重复实现的合并）：
  1. 字段召回：向量检索优先，失败/未加载时降级 DB 关键词匹配
  2. 按表聚合：召回字段 → 表名去重 + MAX_TABLES 裁剪 → 完整表结构（权限裁剪）
  3. schema CSV 生成：供 LLM prompt 使用

修复记录：原 ChatSession._recall_fields 检查 info['fields']['is_built']，
而 get_vector_index_info 返回 key 为 'indexes'，导致向量召回从未生效。
"""
from typing import List, Dict, Optional

from app.logger import logger
from app.permissions import filter_fields_by_permission, get_table_grants_by_schema
from services import schema_service
from core.ret_vector_store import SchemaVectorStore, get_vector_config
from crud.base import session_scope


class SchemaRetriever:
    """Schema 检索器：召回 → 聚合 → CSV"""

    def __init__(self, user: dict = None, user_id: int = None):
        self.user = user or {'user_id': user_id, 'role': 'user'}
        self.user_id = user_id or self.user.get('user_id')
        self.vector_store: Optional[SchemaVectorStore] = None
        self.vector_loaded = False
        self.vector_error: Optional[str] = None

    # ---------- 基础数据访问（权限裁剪在 schema_service 之上叠加） ----------

    @staticmethod
    def _row_to_dict(r) -> Dict:
        return {
            'table_name': r.table_name,
            'column_name': r.column_name,
            'column_description': r.column_description,
            'column_type': r.column_type,
            'column_key': r.column_key,
            'foreign_key': r.foreign_key,
            'sample_values': r.sample_values,
            'sensitive_level': getattr(r, 'sensitive_level', None) or 'public',
        }

    def get_field_rows(self, schema_name: Optional[str] = None,
                       table_names: Optional[List[str]] = None) -> List:
        """按 schema/表名取字段行，并按用户权限裁剪（库级 + 表级 + 字段级）"""
        rows = schema_service.iter_field_rows(
            schema_name=schema_name, table_names=table_names,
            table_grants_by_schema=get_table_grants_by_schema(self.user))
        return filter_fields_by_permission(rows, self.user)

    def field_count(self, schema_name: Optional[str] = None) -> int:
        return schema_service.field_count(schema_name)

    # ---------- 向量索引 ----------

    def try_load_vector_store(self, schema_name: Optional[str] = None) -> bool:
        """尝试加载（必要时构建）向量索引；字段数低于阈值或失败时返回 False"""
        try:
            threshold = get_vector_config('VECTOR_INDEX_THRESHOLD')
            if self.field_count(schema_name) < threshold:
                return False

            store = SchemaVectorStore()
            if store.load(schema_name):
                self.vector_store, self.vector_loaded = store, True
                return True

            schemas = [self._row_to_dict(r) for r in self.get_field_rows(schema_name)]
            if schemas:
                store.build_from_schemas(schemas, schema_name)
                self.vector_store, self.vector_loaded = store, True
                return True
            return False
        except Exception as e:
            self.vector_error = str(e)
            logger.warning(f"[SchemaRetriever] 向量索引加载失败，降级DB查询: {e}")
            return False

    def search_vector(self, keywords: List[str]) -> Optional[List[Dict]]:
        """向量检索字段；未加载或失败时返回 None"""
        if not self.vector_loaded or self.vector_store is None:
            return None
        try:
            keyword_text = ' '.join(keywords)
            return self.vector_store.search_fields(
                keyword_text, top_k=get_vector_config('FIELD_RECALL_TOP_K'))
        except Exception as e:
            logger.warning(f"[SchemaRetriever] 向量检索失败，降级DB查询: {e}")
            return None

    # ---------- 召回 ----------

    def recall_from_db(self, keywords: List[str],
                       schema_name: Optional[str] = None) -> List[Dict]:
        """DB 关键词匹配召回（降级方案）"""
        keyword_set = set(k.lower() for k in keywords)
        results = []
        for r in self.get_field_rows(schema_name):
            table = r.table_name.lower()
            column = r.column_name.lower()
            desc = (r.column_description or '').lower()
            if any(kw in table or kw in column or kw in desc for kw in keyword_set):
                results.append(self._row_to_dict(r))
        return results[:get_vector_config('FIELD_RECALL_TOP_K')]

    def recall_fields(self, keywords: List[str],
                      schema_name: Optional[str] = None) -> List[Dict]:
        """字段召回统一入口：向量优先（懒加载），DB 降级"""
        if not self.vector_loaded and self.vector_error is None:
            self.try_load_vector_store(schema_name)

        results = self.search_vector(keywords)
        if results:
            return results
        return self.recall_from_db(keywords, schema_name)

    # ---------- 聚合 ----------

    def aggregate_tables(self, recalled_fields: List[Dict],
                         schema_name: Optional[str] = None) -> Dict:
        """召回字段 → 表名去重（超限按命中数裁剪）→ 完整表结构"""
        max_tables = get_vector_config('MAX_TABLES')
        table_names = list(set(f.get('table_name') for f in recalled_fields if f.get('table_name')))

        if len(table_names) > max_tables:
            counts: Dict[str, int] = {}
            for f in recalled_fields:
                t = f.get('table_name')
                if t:
                    counts[t] = counts.get(t, 0) + 1
            table_names = sorted(counts, key=counts.get, reverse=True)[:max_tables]

        if not table_names:
            # 未召回任何表时兜底：取前 N 张表（同样受表级权限约束）
            with session_scope() as db:
                tables = schema_service.list_tables(
                    db, schema_name=schema_name,
                    table_grants_by_schema=get_table_grants_by_schema(self.user))
                table_names = [t[0] for t in tables][:max_tables]
        all_fields: Dict[str, Dict] = {}
        if table_names:
            for r in self.get_field_rows(schema_name, table_names):
                key = f"{r.table_name}.{r.column_name}"
                field = self._row_to_dict(r)
                if r.sample_values:
                    samples = [v.strip() for v in r.sample_values.split(',') if v.strip()][:5]
                    if samples:
                        field['sample_values_list'] = samples
                all_fields[key] = field

        return {
            'tables': table_names,
            'all_fields': all_fields,
            'schema_name': schema_name,
        }

    # ---------- CSV ----------

    @staticmethod
    def build_schema_csv(aggregation: Dict) -> str:
        """聚合结果 → CSV 格式 schema 字符串（LLM prompt 用）"""
        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        tables = aggregation.get('tables', [])
        all_fields = aggregation.get('all_fields', {})

        for table in tables:
            table_fields = [(key, field) for key, field in all_fields.items()
                            if field.get('table_name') == table]
            for _key, field in table_fields:
                lines.append(
                    f"{table},{field.get('column_name', '')},"
                    f"{field.get('column_type', '') or ''},"
                    f"{field.get('column_description', '') or ''},"
                    f"{field.get('column_key', '') or ''},"
                    f"{field.get('foreign_key', '') or ''}"
                )

        return '\n'.join(lines)
