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

import json

from app.logger import logger
from app.permissions import filter_fields_by_permission, get_table_grants_by_schema
from services import schema_service
from core.ret_vector_store import SchemaVectorStore, get_vector_config
from core.ret_keywords import KeywordExtractor
from crud.base import session_scope


class SchemaRetriever:
    """Schema 检索器：召回 → 聚合 → CSV"""

    def __init__(self, user: dict = None, user_id: int = None):
        self.user = user or {'user_id': user_id, 'role': 'user'}
        self.user_id = user_id or self.user.get('user_id')
        self.keyword_extractor = KeywordExtractor()
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
            'is_dimension': getattr(r, 'is_dimension', False),
            'is_measure': getattr(r, 'is_measure', False),
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

    def resolve_scope_schema_id(self, schema_name: Optional[str]) -> Optional[int]:
        """库名 → schema id（用于知识作用域过滤；未知库返回 None）"""
        if not schema_name:
            return None
        try:
            with session_scope() as db:
                return schema_service.get_schema_id_by_name(db, schema_name)
        except Exception as e:
            logger.warning(f"[SchemaRetriever] 解析 scope schema id 失败: {e}")
            return None

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

    # ---------- 知识条目单独召回（概念级检索，第三支柱） ----------

    def recall_knowledge(self, query: str, scope_schema_id: Optional[int] = None,
                         keywords: Optional[List[str]] = None) -> Dict:
        """按 query 关键词召回 typed 知识条目，返回注入提示词的文本块与关联表（用于动态扩表）。

        Returns:
            {
              'items':       [{id,title,knowledge_type,aliases,payload,content,score}, ...],
              'prompt_text': str,   # 注入 system prompt【领域知识】的文本块
              'related_tables': [table_name, ...]  # relation 类知识涉及的表（跨库扩表用）
            }
        """
        from crud.knowledge import knowledge_crud
        kws = keywords or self.keyword_extractor.extract(query, top_k=10)
        kw_set = set(k.lower() for k in kws)
        if not kw_set:
            return {'items': [], 'prompt_text': '', 'related_tables': []}

        items = knowledge_crud.search_matched_items(kw_set, scope_schema_id=scope_schema_id, limit=12)
        serialized: List[Dict] = []
        related_tables: List[str] = []
        for d in items:
            serialized.append(d)
            # relation 类型：收集两侧表名用于动态扩表（实现跨库作用域发现）
            if d['knowledge_type'] == 'relation':
                pl = d.get('payload') or {}
                for side in ('left', 'right'):
                    t = (pl.get(side) or {}).get('table')
                    if t and t not in related_tables:
                        related_tables.append(t)

        return {
            'items': serialized,
            'prompt_text': _format_knowledge_prompt(serialized),
            'related_tables': related_tables,
        }

    def extend_aggregation_with_tables(self, aggregation: Dict, table_names: List[str],
                                       schema_name: Optional[str] = None) -> Dict:
        """把额外表（如 relation 知识涉及的表）并入聚合结果，补齐完整字段结构。

        跨库扩表：不过滤 schema_name（传 None），仅按用户权限裁剪，
        从而让 relation 知识把分散在多个数据库中的表自动纳入上下文。
        """
        existing = set(aggregation.get('tables', []))
        to_add = [t for t in table_names if t not in existing]
        if not to_add:
            return aggregation
        for r in self.get_field_rows(None, to_add):
            key = f"{r.table_name}.{r.column_name}"
            if key not in aggregation['all_fields']:
                field = self._row_to_dict(r)
                if r.sample_values:
                    samples = [v.strip() for v in r.sample_values.split(',') if v.strip()][:5]
                    if samples:
                        field['sample_values_list'] = samples
                aggregation['all_fields'][key] = field
        aggregation['tables'] = list(aggregation['tables']) + to_add
        return aggregation

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


# ═══════════════════════════════════════════════════════════════════
# 知识条目 → 提示词渲染（内建类型渲染器；平台不解释具体业务值）
# ═══════════════════════════════════════════════════════════════════

def _render_relation(pl: dict) -> str:
    """将 relation 类型 payload 渲染为可读的 JOIN 描述"""
    left = pl.get('left') or {}
    right = pl.get('right') or {}
    join = pl.get('join_type') or 'INNER JOIN'
    on = pl.get('on')
    if not on:
        lc, rc = left.get('column'), right.get('column')
        if left.get('table') and right.get('table') and lc and rc:
            on = f"{left['table']}.{lc} = {right['table']}.{rc}"
    rel = (f"{left.get('table', '')} {left.get('alias', '')} "
           f"{join} {right.get('table', '')} {right.get('alias', '')} "
           f"ON {on or ''}").strip()
    note = pl.get('note')
    return rel + (f"\n说明: {note}" if note else '')


def _flatten_payload(pl: dict) -> List[str]:
    """通用结构化渲染：顶层键值对（嵌套对象/数组转 JSON）"""
    out = []
    for k, v in pl.items():
        if isinstance(v, (dict, list)):
            out.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
        else:
            out.append(f"{k}={v}")
    return out


def _format_knowledge_prompt(items: List[Dict]) -> str:
    """将召回的知识条目格式化为注入【领域知识】的提示词文本块"""
    if not items:
        return ''
    blocks = []
    for it in items:
        t = it.get('knowledge_type', 'note')
        title = it.get('title') or '(无标题)'
        lines = [f"### [{t}] {title}"]
        content = it.get('content')
        if content:
            lines.append(content)
        payload = it.get('payload')
        if t == 'relation' and isinstance(payload, dict):
            lines.append(_render_relation(payload))
        elif payload and isinstance(payload, dict):
            flat = _flatten_payload(payload)
            if flat:
                lines.append('；'.join(flat))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
