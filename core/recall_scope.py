# -*- coding: UTF-8 -*-
"""召回权限快照（RecallScope）— 召回模块与权限模块的隔离契约

设计见 docs/ChatSQL模块化与全链路留痕设计.md §3.2：
召回只负责"找最相关的"，权限以注入数据参与——SchemaRetriever 消费本模块的
RecallScope 纯数据结构，不 import app.permissions；权限三件套的读取只发生在
build_recall_scope（编排层调用），依赖方向保持 `编排层 → 权限横切模块` 单向。

RecallScope 字段与 app.permissions 的语义对齐（黄金对照见 tests/test_recall_scope.py）：
    visible_schema_ids  get_visible_schema_ids(user)   None=全部可见 / []=无 / [ids]=仅这些
    table_grants        get_table_grants_by_schema(user)
    column_access       get_column_access_map(user)    {column_id: SELECT/FILTER/NONE}（全库口径）
    visible_knowledge_ids  get_visible_knowledge_ids(user)  None=不限制
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.logger import logger


@dataclass
class RecallScope:
    """权限快照：编排层构建后传入召回模块，召回模块只做纯数据过滤"""
    visible_schema_ids: Optional[List[int]] = None      # None=全部可见（admin）
    table_grants: Dict[int, List[int]] = field(default_factory=dict)
    column_access: Dict[int, str] = field(default_factory=dict)
    visible_knowledge_ids: Optional[Set[int]] = None    # None=不限制（admin/通配授权）


def build_recall_scope(user: dict) -> RecallScope:
    """编排层入口：由 user 一次性构建权限快照（内部命中 permissions 的 5s TTL 缓存）

    失败语义与原召回内联实现一致：知识可见性读取失败时降级为不限制（None）；
    其余三项读取失败向上抛（调用方 try/except 降级，见 SchemaRetriever 各方法）。
    """
    from app.permissions import (
        get_column_access_map,
        get_table_grants_by_schema,
        get_visible_knowledge_ids,
        get_visible_schema_ids,
    )
    try:
        knowledge_ids = get_visible_knowledge_ids(user) if user else None
        visible_knowledge_ids = set(knowledge_ids) if knowledge_ids is not None else None
    except Exception as e:
        logger.warning(f"[RecallScope] 知识可见性读取失败，按不限制处理: {e}")
        visible_knowledge_ids = None
    return RecallScope(
        visible_schema_ids=get_visible_schema_ids(user),
        table_grants=get_table_grants_by_schema(user),
        column_access=get_column_access_map(user),
        visible_knowledge_ids=visible_knowledge_ids,
    )
