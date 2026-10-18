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
from models.knowledge import KnowledgeItem, KnowledgeVersion

# 全局常驻条目上限（防 prompt 膨胀）
MAX_PINNED_GLOBAL = 20


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

    def list_global_active(self) -> list:
        """全局发布且启用的条目（人人可见）"""
        return self.list(visibility='global', is_active=1,
                         order_by='updated_at', desc=True)

    def list_global_pinned(self) -> list:
        """全局常驻条目（无条件注入所有对话 prompt），按更新时间倒序"""
        return self.list(visibility='global', is_pinned=1, is_active=1,
                         order_by='updated_at', desc=True)

    def count_global_pinned(self) -> int:
        """当前全局常驻条目数（pin 上限校验用）"""
        with session_scope() as db:
            return db.query(KnowledgeItem).filter(
                KnowledgeItem.visibility == 'global',
                KnowledgeItem.is_pinned == 1,
                KnowledgeItem.is_active == 1).count()

    def hard_delete(self, item_id: int) -> bool:
        """物理删除条目及其全部版本快照（同一事务）。

        先解除 conversations.knowledge_id 的外键引用（置 NULL，不动对话本身），
        否则被对话关联过的条目删除时触发 FOREIGN KEY 约束失败。
        """
        with session_scope() as db:
            from models.conversation import Conversation
            db.query(Conversation).filter(
                Conversation.knowledge_id == item_id).update(
                {'knowledge_id': None}, synchronize_session=False)
            n = db.query(KnowledgeItem).filter(
                KnowledgeItem.id == item_id).delete(
                synchronize_session=False)
            db.query(KnowledgeVersion).filter(
                KnowledgeVersion.item_id == item_id).delete(
                synchronize_session=False)
            return n > 0

    # ---------- 版本快照 ----------

    @staticmethod
    def _snapshot_dict(item: KnowledgeItem) -> dict:
        return {
            'title': item.title,
            'content': item.content,
            'knowledge_type': item.knowledge_type or 'note',
            'aliases': item.aliases,
            'payload': item.payload,
            'scope_schema_id': item.scope_schema_id,
            'visibility': item.visibility or 'personal',
            'is_pinned': item.is_pinned or 0,
            'is_active': item.is_active,
        }

    def record_version(self, item_id: int, action: str,
                       operator_id: Optional[int] = None) -> int:
        """为条目当前状态追加一条版本快照，返回版本号。永不抛出（快照失败不阻断主流程）。"""
        try:
            with session_scope() as db:
                item = db.query(KnowledgeItem).filter(
                    KnowledgeItem.id == item_id).first()
                if not item:
                    return 0
                last = db.query(KnowledgeVersion.version_no).filter(
                    KnowledgeVersion.item_id == item_id).order_by(
                    KnowledgeVersion.version_no.desc()).first()
                version_no = (last[0] + 1) if last else 1
                db.add(KnowledgeVersion(
                    item_id=item_id, version_no=version_no, action=action,
                    snapshot=json.dumps(self._snapshot_dict(item), ensure_ascii=False),
                    operator_id=operator_id))
                return version_no
        except Exception:
            return 0

    def list_versions(self, item_id: int) -> List[dict]:
        """条目版本列表（含快照），按版本号倒序，附操作人用户名"""
        with session_scope() as db:
            from models.user import User
            rows = db.query(KnowledgeVersion, User.username).outerjoin(
                User, User.id == KnowledgeVersion.operator_id).filter(
                KnowledgeVersion.item_id == item_id).order_by(
                KnowledgeVersion.version_no.desc()).all()
            out = []
            for v, uname in rows:
                out.append({
                    'version_no': v.version_no,
                    'action': v.action,
                    'snapshot': _parse_json(v.snapshot, {}),
                    'operator_id': v.operator_id,
                    'operator_name': uname,
                    'created_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S') if v.created_at else None,
                })
            return out

    def get_version_snapshot(self, item_id: int, version_no: int) -> Optional[dict]:
        """取指定版本快照"""
        with session_scope() as db:
            v = db.query(KnowledgeVersion).filter(
                KnowledgeVersion.item_id == item_id,
                KnowledgeVersion.version_no == version_no).first()
            return _parse_json(v.snapshot, None) if v else None

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
            'visibility': (item.visibility or 'personal'),
            'is_pinned': (item.is_pinned or 0),
            'is_active': item.is_active,
            'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
            'updated_at': item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else None,
        }

    # ---------- 召回 ----------

    def search_matched_items(self, keyword_set: Set[str], scope_schema_id: Optional[int] = None,
                             limit: int = 12, owner_user_id: Optional[int] = None,
                             visible_ids: Optional[Set[int]] = None) -> List[dict]:
        """按关键词集合召回知识条目（打分排序），返回已序列化的字典列表。

        - 匹配范围：title + aliases(JSON) + content + payload(JSON 文本)
        - 作用域：scope_schema_id 为 NULL（全局）或匹配传入 schema id 的条目；
          relation 类型忽略 scope 限制（关系天然跨库，用于动态扩表）
        - 可见性（owner_user_id/visible_ids 任一传入即启用）：
          visibility=global 的条目人人可召回；personal 条目仅属主或被授权者
          （visible_ids 来自 get_visible_knowledge_ids，None=无限制，set=白名单）
        - 匹配下推到 SQL LIKE：先按关键词粗筛出候选集，再在内存中打分排序，
          避免把全部知识条目 all() 进内存（条目多时是全表扫描 + Python 循环）
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

            # 可见性下推：global 人人可见；personal 仅属主/被授权者
            if owner_user_id is not None or visible_ids is not None:
                vis_conds = [KnowledgeItem.visibility == 'global']
                if owner_user_id is not None:
                    vis_conds.append(KnowledgeItem.user_id == owner_user_id)
                if visible_ids:  # 空集合 = 无授权，不加条件
                    vis_conds.append(KnowledgeItem.id.in_(visible_ids))
                q = q.filter(or_(*vis_conds))

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
