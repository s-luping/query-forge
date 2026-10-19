# -*- coding: UTF-8 -*-
"""共享 Schema 检索器 — 多轮对话（gen_chat.py）共用的召回层

职责（原 SQLPipeline 与 ChatSession 两份重复实现的合并）：
  1. 字段召回：向量检索优先，失败/未加载时降级 DB 关键词匹配
  2. 按表聚合：召回字段 → 表名去重 + MAX_TABLES 裁剪 → 完整表结构（权限裁剪）
  3. schema CSV 生成：供 LLM prompt 使用

修复记录：原 ChatSession._recall_fields 检查 info['fields']['is_built']，
而 get_vector_index_info 返回 key 为 'indexes'，导致向量召回从未生效。
"""
import json
from typing import Dict, List, Optional

import numpy as np

from app.logger import logger
from app.permissions import (
    filter_fields_by_permission,
    get_table_grants_by_schema,
    get_visible_schema_ids,
)
from core.ret_keywords import KeywordExtractor
from core.ret_vector_store import SchemaVectorStore, get_vector_config
from crud.base import session_scope
from crud.schema import relation_crud
from services import schema_service


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
            'schema_name': getattr(r, 'schema_name', None),
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
        visible = get_visible_schema_ids(self.user)
        rows = schema_service.iter_field_rows(
            schema_name=schema_name, table_names=table_names,
            visible_schema_ids=visible,
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
        """尝试加载向量索引（不再自动构建）；字段数低于阈值或失败时返回 False

        全库统一索引：始终加载无前缀 fields 索引（schema_name 仅记录用途）。
        - 索引状态为 stale（导入/同步后标记）时，用旧索引继续服务，
          重建统一由定时任务「向量索引重建」执行，避免与用户使用冲突。
        - 无索引文件时降级 DB 关键词召回，等待定时任务首次构建。
        """
        try:
            threshold = get_vector_config('VECTOR_INDEX_THRESHOLD')
            if self.field_count(None) < threshold:
                return False

            store = SchemaVectorStore()
            if store.load(None):
                self.vector_store, self.vector_loaded = store, True
                self._log_stale_status()
                return True

            # 无索引文件：不再前台构建，等待定时任务构建（期间降级 DB 召回）
            logger.info("[SchemaRetriever] 向量索引尚未构建，本次召回降级 DB 查询，等待定时任务构建")
            return False
        except Exception as e:
            self.vector_error = str(e)
            logger.warning(f"[SchemaRetriever] 向量索引加载失败，降级DB查询: {e}")
            return False

    def _log_stale_status(self):
        """索引状态为 stale 时仅记录日志（重建统一由定时任务执行）。

        旧索引文件保持完整（原子写），本次召回继续用旧索引服务，
        定时任务「向量索引重建」检测到 stale 后按需构建替换。
        """
        try:
            from core.ret_index_meta import get_index_meta
            meta = get_index_meta('default')
            if meta and meta.get('status') == 'stale':
                logger.info("[SchemaRetriever] 向量索引为 stale，等待定时任务重建（本次召回使用旧索引）")
        except Exception as e:
            logger.warning(f"[SchemaRetriever] stale 状态检查失败: {e}")

    def search_vector(self, keywords: List[str],
                      query: Optional[str] = None,
                      schema_name: Optional[str] = None) -> Optional[List[Dict]]:
        """向量检索字段；未加载或失败时返回 None

        编码文本优先使用原始 query（完整语义），未提供时回退关键词拼接。
        构建权限掩码，剔除用户无权限字段参与 top-K 竞争。
        """
        if not self.vector_loaded or self.vector_store is None:
            return None
        try:
            text = (query or '').strip() or ' '.join(keywords)
            mask = self._build_search_mask(schema_name)
            return self.vector_store.search_fields(
                text, top_k=get_vector_config('FIELD_RECALL_TOP_K'), mask=mask)
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

    def _build_search_mask(self, schema_name: Optional[str] = None) -> Optional[np.ndarray]:
        """构建向量搜索权限掩码：仅允许用户可见的字段参与 top-K 竞争。

        索引为全库索引（含所有库字段），用户可能只对部分库/表有权限。
        把无权限字段的相似度排除，避免 top-K 名额被不可见字段挤占。
        返回 None 表示无需掩码（管理员全可见或索引未加载）。
        """
        try:
            import numpy as np
            store = self.vector_store
            if store is None or not store.field_index.is_built:
                return None
            metas = store.field_index.metadata
            if not metas:
                return None
            # 管理员（无权限限制）直接放行
            visible = get_visible_schema_ids(self.user)
            if visible is None:
                return None
            # 可见 schema id → 库名集合（掩码按库名匹配索引 metadata）
            from models.schema import DbSchema
            with session_scope() as db:
                visible_names = set(
                    name for (name,) in db.query(DbSchema.name).filter(
                        DbSchema.id.in_(visible)).all()
                )
            # 单库模式：仅保留该库字段
            if schema_name:
                mask = np.array([
                    m.get('schema_name') == schema_name for m in metas
                ], dtype=bool)
                return mask if mask.any() else None
            # 全库模式：保留可见库 + 未标库名的字段（旧索引兼容）
            mask = np.array([
                (not m.get('schema_name')) or (m.get('schema_name') in visible_names)
                for m in metas
            ], dtype=bool)
            return mask if mask.any() else None
        except Exception as e:
            logger.warning(f"[SchemaRetriever] 构建搜索掩码失败，放行全量: {e}")
            return None

    def list_schema_tables(self, schema_name: str) -> List[str]:
        """权限约束下的库内表名列表（库级 + 表级权限裁剪）"""
        with session_scope() as db:
            tables = schema_service.list_tables(
                db, schema_name=schema_name,
                visible_schema_ids=get_visible_schema_ids(self.user),
                table_grants_by_schema=get_table_grants_by_schema(self.user))
            return [t[0] for t in tables]

    def recall_fields(self, keywords: List[str],
                      schema_name: Optional[str] = None,
                      query: Optional[str] = None) -> List[Dict]:
        """字段召回统一入口：向量优先（懒加载）+ DB 关键词兜底合并。

        - 小库直通：指定库且表数不超过 SMALL_SCHEMA_TABLE_LIMIT 时跳过召回，
          每表返回一个 full_scope 标记的占位字段，整库进入上下文。
          十几张表的库全量 CSV 仅千余 token，字段召回 TopK 截断反而会丢核心表
          （如 formula_1 的 drivers/races 未召回导致两模型一致误拦截）。
        - 向量索引可能是历史构建（缺库/权限范围不一致），仅靠向量会漏召回
          未建索引库的表 → 用 DB 关键词召回做并集兜底，保证覆盖所有可见库。
          向量在位时兜底保留 top_k//3 名额（防向量满载把兜底整体挤出）；
          无向量结果时兜底全量返回（原降级行为不变）。
        - 两条路径返回字段均以 DB 权限集合过滤/归一化（schema_name/column_name）。
        - 结果去重（同一字段以 DB 权威结构为准）。
        - query: 原始用户问题，用于向量编码（语义完整度高于关键词拼接）。
        - 全库索引下用权限掩码避免 top-K 名额被无权限字段挤占。
        """
        if schema_name:
            try:
                all_tables = self.list_schema_tables(schema_name)
                if 0 < len(all_tables) <= get_vector_config('SMALL_SCHEMA_TABLE_LIMIT'):
                    return [{'schema_name': schema_name, 'table_name': t,
                             'column_name': '', 'recall_source': 'full',
                             'full_scope': True}
                            for t in all_tables]
            except Exception as e:
                logger.warning(f"[SchemaRetriever] 小库直通判定失败，走常规召回: {e}")

        if not self.vector_loaded and self.vector_error is None:
            self.try_load_vector_store(schema_name)

        results = self.search_vector(keywords, query=query, schema_name=schema_name)
        merged: List[Dict] = []
        seen = set()
        if results:
            for d in self._filter_recalled_by_permission(results, schema_name):
                key = (d.get('schema_name') or '', d.get('table_name', ''),
                       d.get('column_name', ''))
                if key not in seen:
                    seen.add(key)
                    # 标记来源：向量召回语义相关度高，聚合裁剪时优先保留
                    d['recall_source'] = 'vector'
                    merged.append(d)
        # DB 关键词召回（已按权限过滤）并集补充，覆盖向量索引缺失的库/表。
        # 向量在位时必须给兜底保留固定名额（top_k//3）：此前按"先向量后兜底"
        # 整体截断，向量满载 top_k 条时 DB 兜底会被 100% 挤出——
        # 「科目」等列描述子串命中的字段永远进不了上下文（并集保证覆盖的意图失效）。
        # 无向量结果时兜底全量返回（保持原降级行为）。
        top_k = get_vector_config('FIELD_RECALL_TOP_K')
        db_quota = max(1, top_k // 3) if merged else top_k
        db_kept: List[Dict] = []
        for d in self.recall_from_db(keywords, schema_name)[:db_quota]:
            key = (d.get('schema_name') or '', d.get('table_name', ''),
                   d.get('column_name', ''))
            if key not in seen:
                seen.add(key)
                d['recall_source'] = 'db'
                db_kept.append(d)
        merged.extend(db_kept)
        # 超出 top_k 时截断：向量结果让出 db_kept 同等名额，保证兜底不被挤掉
        if len(merged) > top_k:
            merged = merged[:max(0, top_k - len(db_kept))] + db_kept
        return merged

    def _filter_recalled_by_permission(self, recalled: List[Dict],
                                       schema_name: Optional[str] = None) -> List[Dict]:
        """按当前用户权限过滤向量召回结果（DB 权限集合为权威）

        向量索引可能构建于权限更宽的时期，或为全量索引；
        召回字段若不在当前用户可见字段集合内则剔除。
        同时把向量索引的 field_name 结构统一为 DB 的 column_name + schema_name，
        保证下游聚合/CSV/链路日志读取的字段一致。
        """
        if not recalled:
            return recalled
        try:
            table_names = list({f.get('table_name') for f in recalled if f.get('table_name')})
            allowed = {}
            allowed_flat = {}   # (table, column) → field dict，兼容旧向量索引（无 schema 信息）
            for r in self.get_field_rows(schema_name, table_names or None):
                d = self._row_to_dict(r)
                allowed[(r.schema_name or '', r.table_name, r.column_name)] = d
                allowed_flat.setdefault((r.table_name, r.column_name), d)
            filtered = []
            for f in recalled:
                table = f.get('table_name', '')
                field = f.get('field_name') or f.get('column_name', '')
                key = (f.get('schema_name') or '', table, field)
                d = allowed.get(key)
                if d is None:
                    d = allowed_flat.get((table, field))
                if d is not None:
                    filtered.append(d)
            return filtered
        except Exception as e:
            logger.warning(f"[SchemaRetriever] 召回权限过滤失败，放行: {e}")
            return recalled

    # ---------- 聚合 ----------

    def aggregate_tables(self, recalled_fields: List[Dict],
                         schema_name: Optional[str] = None,
                         keep_first: Optional[set] = None) -> Dict:
        """召回字段 → 表名去重（超限按命中数裁剪）→ 完整表结构

        keep_first: 优先保留的表名集合（追问轮首轮表）。超限时首轮表完整保留，
        仅对新增召回表按命中数裁剪到剩余名额，避免追问上下文缩水。
        此前累积路径把首轮表混入后按 MAX_TABLES 随机裁剪（无命中数时排序不稳定），
        导致首轮 15 张表被挤到 10 张。
        """
        # 保持输入顺序（追问轮传 merged_order 保序列表；同名列去重/白名单裁剪依赖稳定表序）
        table_names = list(dict.fromkeys(
            f.get('table_name') for f in recalled_fields if f.get('table_name')))

        # 小库直通：召回带 full_scope 标记时整库注入，不受 MAX_TABLES 裁剪
        full_scope = any(f.get('full_scope') for f in recalled_fields)
        max_tables = get_vector_config('MAX_TABLES')
        if full_scope:
            max_tables = max(max_tables, len(table_names))

        if len(table_names) > max_tables:
            # 权重裁剪：向量召回字段(recall_source=vector)所在表优先保留，
            # DB 子串兜底命中的表（权重低）只在剩余名额内补充——
            # 避免"项目/广告费"这类子串在大量无关表中命中导致聚合混入杂表。
            counts: Dict[str, int] = {}
            for f in recalled_fields:
                t = f.get('table_name')
                if t:
                    # 权重：向量(10) > 知识扩表(5) > DB 子串兜底(1)。
                    # 知识扩表是"口径知识确认相关"的表（如 entity_map 声明的 DM 事实表），
                    # 不应与子串噪声表同权竞争裁剪名额。
                    src = f.get('recall_source')
                    w = 10 if src == 'vector' else (5 if src == 'knowledge' else 1)
                    counts[t] = counts.get(t, 0) + w
            if keep_first:
                first_names = [t for t in table_names if t in keep_first]
                rest = [t for t in table_names if t not in keep_first]
                if len(first_names) >= max_tables:
                    table_names = first_names
                else:
                    rest = sorted(rest, key=lambda t: counts.get(t, 0), reverse=True)
                    table_names = first_names + rest[:max_tables - len(first_names)]
            else:
                table_names = sorted(counts, key=counts.get, reverse=True)[:max_tables]

        if not table_names:
            # 未召回任何表时兜底：取前 N 张表（库级 + 表级权限约束）
            with session_scope() as db:
                tables = schema_service.list_tables(
                    db, schema_name=schema_name,
                    visible_schema_ids=get_visible_schema_ids(self.user),
                    table_grants_by_schema=get_table_grants_by_schema(self.user))
                table_names = [t[0] for t in tables][:max_tables]
        all_fields: Dict[str, Dict] = {}
        if table_names:
            for r in self.get_field_rows(schema_name, table_names):
                # key 带库名前缀消歧（跨库同名表场景）
                key = f"{r.schema_name}.{r.table_name}.{r.column_name}"
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
            'full_scope': full_scope,
        }

    # ---------- 知识条目单独召回（概念级检索，第三支柱） ----------

    def recall_knowledge(self, query: str, scope_schema_id: Optional[int] = None,
                         keywords: Optional[List[str]] = None,
                         exclude_contents: Optional[set] = None) -> Dict:
        """按 query 关键词召回 typed 知识条目，返回注入提示词的文本块与关联表（用于动态扩表）。

        exclude_contents: 已注入 prompt 的知识内容集合（如用户勾选知识库的 content），
        命中条目按 content 精确去重，避免同一知识在【领域知识】中出现两次。

        Returns:
            {
              'items':       [{id,title,knowledge_type,aliases,payload,content,score}, ...],
              'prompt_text': str,   # 注入 system prompt【领域知识】的文本块
              'related_tables': [table_name, ...]  # relation 类两侧表 + 其他类型
                                                    # payload.related_tables 声明的表（跨库扩表用）
            }
        """
        from crud.knowledge import knowledge_crud
        kws = keywords or self.keyword_extractor.extract(query, top_k=10)
        kw_set = set(k.lower() for k in kws)
        if not kw_set:
            return {'items': [], 'prompt_text': '', 'related_tables': []}

        # 可见性：global 条目人人可召回；personal 仅属主/被授权者
        # （get_visible_knowledge_ids 对管理员/通配授权返回 None = 不限制）
        owner_user_id = self.user_id
        visible_ids = None
        try:
            from app.permissions import get_visible_knowledge_ids
            ids = get_visible_knowledge_ids(self.user) if self.user else None
            visible_ids = set(ids) if ids is not None else None
        except Exception:
            pass

        items = knowledge_crud.search_matched_items(
            kw_set, scope_schema_id=scope_schema_id, limit=12,
            owner_user_id=owner_user_id, visible_ids=visible_ids)
        if exclude_contents:
            items = [d for d in items
                     if (d.get('content') or '').strip() not in exclude_contents]
        serialized: List[Dict] = []
        related_tables: List[str] = []
        for d in items:
            serialized.append(d)
            pl = d.get('payload') or {}
            # relation 类型：收集两侧表名用于动态扩表（实现跨库作用域发现）
            if d['knowledge_type'] == 'relation':
                for side in ('left', 'right'):
                    t = (pl.get(side) or {}).get('table')
                    if t and t not in related_tables:
                        related_tables.append(t)
            # 其他类型（entity_map/note 等）：payload.related_tables 显式声明关联表，
            # 作为「口语词 → 事实表」的桥接。背景：向量召回按列名/描述语义排序，
            # 「费用合计/EETotal/AA0003」这类业务问法排不进 top-K 时（列名是通用英文、
            # 无采样值），由命中的知识条目把事实表补进上下文，避免判断步因表缺失误拦截。
            for t in (pl.get('related_tables') or []):
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
            # key 与 aggregate_tables 保持一致（库名.表名.字段名 消歧）
            key = f"{r.schema_name}.{r.table_name}.{r.column_name}"
            if key not in aggregation['all_fields']:
                field = self._row_to_dict(r)
                if r.sample_values:
                    samples = [v.strip() for v in r.sample_values.split(',') if v.strip()][:5]
                    if samples:
                        field['sample_values_list'] = samples
                aggregation['all_fields'][key] = field
        aggregation['tables'] = list(aggregation['tables']) + to_add
        return aggregation

    # ---------- 表关系召回（人工维护的 JOIN 提示，注入 prompt） ----------

    def get_relations_text(self, table_names: Optional[List[str]],
                           max_relations: int = 30) -> str:
        """按聚合命中的表匹配表间关系，渲染为 JOIN 提示文本。

        仅返回两侧表都在上下文中的关系（另一侧表不在 schema CSV 中时，
        给出连接条件反而会诱导模型使用不存在的表）。
        失败静默返回空字符串（关系提示是增强信息，不阻断主流程）。
        """
        if not table_names:
            return ''
        # 兼容跨库表名（库名.表名）：关系匹配用纯表名（关系定义本身不区分库），
        # 但输出时若上下文表名带库前缀，则同步给输出补前缀避免诱导使用不存在的表
        tables = set(table_names)
        pure_tables = {t.split('.', 1)[1] if '.' in t else t for t in tables}
        try:
            visible = get_visible_schema_ids(self.user)
            if visible == []:
                return ''
            # None = 管理员/未配置权限，可见全部 schema
            relations = (relation_crud.list_by_schemas(visible)
                         if visible is not None
                         else relation_crud.list_all(order_by='id'))
            lines = []
            for r in relations:
                if r.left_table in pure_tables and r.right_table in pure_tables:
                    desc = f" — {r.description}" if r.description else ''
                    # 输出用上下文中的原始表名（含前缀，若召回时带库名）
                    left_label = next((t for t in tables if t == r.left_table
                                       or t.endswith('.' + r.left_table)), r.left_table)
                    right_label = next((t for t in tables if t == r.right_table
                                        or t.endswith('.' + r.right_table)), r.right_table)
                    lines.append(
                        f"{left_label}.{r.left_column} = {right_label}.{r.right_column}"
                        f" ({r.join_type or 'INNER JOIN'}, {r.relation_type or '1:N'}){desc}"
                    )
                    if len(lines) >= max_relations:
                        break
            return '\n'.join(lines)
        except Exception as e:
            logger.warning(f"[SchemaRetriever] 表关系召回失败: {e}")
            return ''

    # ---------- CSV ----------

    def build_full_schema_csv(self, schema_name: Optional[str] = None) -> str:
        """全量重建 schema CSV（追问轮 fallback：旧对话未存首轮表集合时用）

        权限裁剪（库级 + 表级 + 字段级）统一走 get_field_rows——路由层不再
        自行拼权限原语，避免遗漏某级裁剪造成数据泄漏（2026-10-17 修过一次）。
        """
        rows = self.get_field_rows(schema_name)
        if not rows:
            return "表名,字段名,字段类型,字段描述,主键,外键"

        # 按表分组（同表字段聚合；get_field_rows 未按表连续返回时仍稳定分组）
        cross_schema = schema_name is None and len({r.schema_name for r in rows}) > 1
        tables = {}
        for f in rows:
            tables.setdefault(f.table_name, []).append(f)

        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        for table_name, fields in tables.items():
            for f in fields:
                label = f"{f.schema_name}.{table_name}" if cross_schema else table_name
                lines.append(
                    f"{label},{f.column_name or ''},"
                    f"{f.column_type or ''},"
                    f"{f.column_description or ''},"
                    f"{f.column_key or ''},"
                    f"{f.foreign_key or ''}"
                )
        return '\n'.join(lines)

    @staticmethod
    def build_schema_csv(aggregation: Dict,
                         fields_whitelist: Optional[set] = None) -> str:
        """聚合结果 → CSV 格式 schema 字符串（LLM prompt 用）

        跨库模式（召回涉及多个 schema）下表名带库名前缀（库名.表名），
        供 LLM 生成跨库 SQL 时区分同名表；单库模式保持纯表名（兼容旧行为）。

        fields_whitelist: {(表名, 字段名), ...} — 非空时仅输出白名单字段，
        并自动补齐主键(PRI)与外键列（保证 JOIN 关联可用）。
        首轮/单次生成不传（需要完整表结构）；追问轮传「历史 SQL 引用列 ∪ 本轮
        召回列 ∪ 知识扩表全列」（知识表无召回列，白名单须显式保留其全部字段）。
        """
        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        tables = aggregation.get('tables', [])
        all_fields = aggregation.get('all_fields', {})

        # 判断是否带库前缀：跨库模式（召回涉及多个库）或全库召回（schema_name=None，SQL 需带前缀才能路由执行）
        schema_names = {f.get('schema_name') for f in all_fields.values()
                        if f.get('schema_name')}
        cross_schema = aggregation.get('schema_name') is None or len(schema_names) > 1

        for table in tables:
            table_fields = [(key, field) for key, field in all_fields.items()
                            if field.get('table_name') == table]
            for _key, field in table_fields:
                if fields_whitelist:
                    col = field.get('column_name', '')
                    is_pk = field.get('column_key') == 'PRI'
                    has_fk = bool(field.get('foreign_key'))
                    if (table, col) not in fields_whitelist and not is_pk and not has_fk:
                        continue
                # 跨库时显示 库名.表名（同库多 schema 场景下精确到库）
                label = table
                if cross_schema and field.get('schema_name'):
                    label = f"{field['schema_name']}.{table}"
                lines.append(
                    f"{label},{field.get('column_name', '')},"
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
