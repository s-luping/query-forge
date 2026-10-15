# -*- coding: UTF-8 -*-
"""crud.knowledge — 知识库数据访问

用法：
    from crud.knowledge import knowledge_crud
    items = knowledge_crud.list_active(user_id=1)
    matched = knowledge_crud.search_matched_items(keyword_set, scope_schema_id=1)
"""
import json
from typing import List, Optional, Set

from crud.base import BaseCrud, session_scope
from models.knowledge import KnowledgeItem


def _parse_json(text, default):
    """解析 JSON 文本，失败或为空返回 default"""
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


class KnowledgeCrud(BaseCrud):
    model = KnowledgeItem

    def get_active(self, item_id: int) -> Optional[KnowledgeItem]:
        return self.get_one(id=item_id, is_active=1)

    def list_by_user(self, user_id: int) -> list:
        return self.list(user_id=user_id, order_by='created_at', desc=True)

    def list_active(self, user_id: Optional[int] = None) -> list:
        if user_id is not None:
            return self.list(user_id=user_id, is_active=1,
                             order_by='created_at', desc=True)
        return self.list(is_active=1, order_by='created_at', desc=True)

    def list_all_visible(self, user_id: int) -> list:
        """管理员看全部启用条目；普通用户看自己创建的启用条目"""
        return self.list_active(user_id=user_id)

    # ---------- typed 序列化 ----------

    @staticmethod
    def to_dict(item: KnowledgeItem) -> dict:
        """统一序列化：含 typed 字段，NULL knowledge_type 归一成 'note'"""
        return {
            'id': item.id,
            'user_id': item.user_id,
            'title': item.title,
            'content': item.content or '',
            'knowledge_type': (item.knowledge_type or 'note'),
            'aliases': _parse_json(item.aliases, []),
            'payload': _parse_json(item.payload, {}),
            'scope_schema_id': item.scope_schema_id,
            'is_active': item.is_active,
            'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
            'updated_at': item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else None,
        }

    # ---------- 召回 ----------

    def search_matched_items(self, keyword_set: Set[str], scope_schema_id: Optional[int] = None,
                             limit: int = 12) -> List[dict]:
        """按关键词集合召回知识条目（打分排序），返回已序列化的字典列表。

        - 匹配范围：title + aliases(JSON) + content + payload(JSON 文本)
        - 作用域：scope_schema_id 为 NULL（全局）或匹配传入 schema id 的条目；
          relation 类型忽略 scope 限制（关系天然跨库，用于动态扩表）
        - 匹配下推到 SQL LIKE：先按关键词粗筛出候选集，再在内存中打分排序，
          避免把全部知识条目 all() 进内存（条目多时是全表扫描 + Python 循环）。
        - 在会话内完成序列化，避免返回分离对象后因属性过期触发 DetachedInstanceError
        - 返回字典（含 score）列表，top `limit`
        """
        if not keyword_set:
            return []
        # 过滤空关键词（LIKE '%%' 会匹配所有行）
        kws = [k for k in keyword_set if k and k.strip()]
        if not kws:
            return []

        with session_scope() as db:
            from sqlalchemy import or_
            q = db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1)

            # 作用域下推（relation 类型豁免）
            if scope_schema_id is not None:
                q = q.filter(or_(
                    KnowledgeItem.knowledge_type == 'relation',
                    KnowledgeItem.scope_schema_id.is_(None),
                    KnowledgeItem.scope_schema_id == scope_schema_id,
                ))

            # 关键词 LIKE 粗筛：任一关键词命中任一可匹配字段即进入候选集
            like_conds = []
            for kw in kws:
                like_conds.append(or_(
                    KnowledgeItem.title.like(f'%{kw}%'),
                    KnowledgeItem.aliases.like(f'%{kw}%'),
                    KnowledgeItem.content.like(f'%{kw}%'),
                    KnowledgeItem.payload.like(f'%{kw}%'),
                ))
            q = q.filter(or_(*like_conds))

            # 候选集通常已大幅缩小，再在内存中精确打分
            results = []
            for it in q.all():
                aliases = _parse_json(it.aliases, [])
                alias_text = ' '.join(aliases) if isinstance(aliases, list) else ''
                haystack = ' '.join([
                    it.title or '',
                    alias_text,
                    it.content or '',
                    it.payload or '',
                ]).lower()
                score = sum(1 for kw in kws if kw and kw.lower() in haystack)
                if score > 0:
                    d = self.to_dict(it)
                    d['score'] = score
                    results.append(d)
            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:limit]


knowledge_crud = KnowledgeCrud()
