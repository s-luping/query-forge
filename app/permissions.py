# -*- coding: UTF-8 -*-
"""权限校验 — admin/user 两级，授权基于外键关联表

可见性语义（对 schema 与知识一致）：
    None  = 全部可见（admin 或持有 schema_id/knowledge_id 为 NULL 的"全量"授权）
    []    = 无可见资源
    [ids] = 仅这些资源可见

字段级权限（三级）：
    SELECT  — 完全可读，可出现在 SQL 任意子句
    FILTER  — 可用不可见：允许 WHERE/JOIN/GROUP BY/HAVING，禁止 SELECT 列表
    NONE    — 完全不可用

默认行为（无显式 UserColumnGrant 时）按 sensitive_level 推导：
    public        → SELECT
    internal      → SELECT
    sensitive     → FILTER
    confidential  → NONE
"""
from typing import Optional, Dict, List

from models import SessionLocal
from models.user import UserSchemaGrant, UserKnowledgeGrant, UserTableGrant
from models.security import UserColumnGrant, RowScopeRule
from models.schema import DbColumn, DbTable, DbSchema


def is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def get_visible_schema_ids(user: dict) -> Optional[list]:
    """获取用户可见的 schema_id 列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    db = SessionLocal()
    try:
        records = db.query(UserSchemaGrant).filter(
            UserSchemaGrant.user_id == user['user_id']).all()
        if not records:
            return []
        ids = [r.schema_id for r in records]
        if None in ids:
            return None
        return ids
    finally:
        db.close()


def is_schema_visible(user: dict, schema_name: Optional[str]) -> bool:
    """按库名校验用户可见性（None/空库名视为可）。供生成链路入口二次校验，防绕过前端。"""
    if not schema_name or is_admin(user):
        return True
    visible = get_visible_schema_ids(user)
    if visible is None:
        return True
    db = SessionLocal()
    try:
        sid = db.query(DbSchema.id).filter(DbSchema.name == schema_name).first()
    finally:
        db.close()
    return sid is not None and sid[0] in visible


def get_visible_knowledge_ids(user: dict) -> Optional[list]:
    """获取用户可见的知识库条目 ID 列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    db = SessionLocal()
    try:
        records = db.query(UserKnowledgeGrant).filter(
            UserKnowledgeGrant.user_id == user['user_id']).all()
        if not records:
            return []
        ids = [r.knowledge_id for r in records]
        if None in ids:
            return None
        return ids
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 表级权限（第三层：库 → 表 → 字段）
# 语义：同一 schema 内配置了任意表授权 → 该用户仅可见名单内的表；
#       未配置任何表授权的 schema → 全部表可见（默认）。
# ═══════════════════════════════════════════════════════════════════

def get_table_grants_by_schema(user: dict) -> Dict[int, List[int]]:
    """用户配置过的表级白名单 {schema_id: [table_id, ...]}。

    返回 {} 表示没有任何表级限制（全部可见）；key 出现即表示该 schema 受限。
    admin 恒为 {}（无表级限制）。
    """
    if is_admin(user):
        return {}
    db = SessionLocal()
    try:
        rows = (db.query(DbTable.schema_id, UserTableGrant.table_id)
                .join(UserTableGrant, UserTableGrant.table_id == DbTable.id)
                .filter(UserTableGrant.user_id == user['user_id']).all())
        result: Dict[int, List[int]] = {}
        for schema_id, table_id in rows:
            result.setdefault(schema_id, []).append(table_id)
        return result
    finally:
        db.close()


def is_table_visible(user: dict, schema_id: int, table_id: int,
                     grants_by_schema: Optional[Dict[int, List[int]]] = None) -> bool:
    """表可见性判断（单表）。"""
    if is_admin(user):
        return True
    if grants_by_schema is None:
        grants_by_schema = get_table_grants_by_schema(user)
    ids = grants_by_schema.get(schema_id)
    if ids is None:
        return True  # 该 schema 未配置表级白名单 → 全部可见
    return table_id in ids


def filter_tables_by_permission(rows, user: dict,
                                schema_id_attr: str = 'schema_id',
                                table_id_attr: str = 'id') -> list:
    """过滤表行列表：仅保留用户可见的表（行对象需含 schema_id / id 属性）。"""
    if is_admin(user) or not rows:
        return rows
    grants = get_table_grants_by_schema(user)
    if not grants:
        return rows
    return [r for r in rows
            if is_table_visible(user, getattr(r, schema_id_attr),
                               getattr(r, table_id_attr), grants)]


# ═══════════════════════════════════════════════════════════════════
# 字段级权限
# ═══════════════════════════════════════════════════════════════════

_SENSITIVE_DEFAULTS = {
    'public': 'SELECT',
    'internal': 'SELECT',
    'sensitive': 'FILTER',
    'confidential': 'NONE',
}


def get_column_access_map(user: dict, schema_name: Optional[str] = None,
                          table_names: Optional[List[str]] = None) -> Dict[int, str]:
    """获取字段级权限映射 {column_id: access_type}。

    admin → 全部 SELECT
    非 admin → 先按 sensitive_level 推导默认值，再用 UserColumnGrant 覆盖
    """
    if is_admin(user):
        return {}

    db = SessionLocal()
    try:
        q = (db.query(DbColumn.id, DbColumn.sensitive_level)
             .join(DbTable, DbColumn.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if schema_name:
            q = q.filter(DbSchema.name == schema_name)
        if table_names:
            q = q.filter(DbTable.name.in_(table_names))
        rows = q.all()

        result = {}
        for col_id, level in rows:
            result[col_id] = _SENSITIVE_DEFAULTS.get(level or 'public', 'SELECT')

        # 覆盖显式授权
        col_ids = list(result.keys())
        if col_ids:
            grants = db.query(UserColumnGrant).filter(
                UserColumnGrant.user_id == user['user_id'],
                UserColumnGrant.column_id.in_(col_ids)
            ).all()
            for g in grants:
                result[g.column_id] = g.access_type

        return result
    finally:
        db.close()


def filter_fields_by_permission(rows, user: dict) -> list:
    """过滤字段行：只保留用户有 SELECT 或 FILTER 权限的字段。

    用于 Schema 裁剪——LLM prompt 只注入用户可用的字段。
    SELECT 和 FILTER 级别的字段都注入（FILTER 字段可用于条件但不返回）。
    NONE 级别字段完全剔除。
    """
    if is_admin(user):
        return rows
    if not rows:
        return rows

    col_ids = [getattr(r, 'column_id', 0) for r in rows if getattr(r, 'column_id', 0)]
    if not col_ids:
        return rows

    access_map = get_column_access_map(user)
    return [r for r in rows if access_map.get(getattr(r, 'column_id', 0), 'SELECT') != 'NONE']


def get_row_scope_rules(user: dict, table_names: Optional[List[str]] = None) -> Dict[str, str]:
    """获取行级过滤规则 {table_name: filter_expression}"""
    if is_admin(user):
        return {}

    db = SessionLocal()
    try:
        q = (db.query(DbTable.name, RowScopeRule.filter_expression)
             .join(RowScopeRule, RowScopeRule.table_id == DbTable.id)
             .filter(RowScopeRule.user_id == user['user_id']))
        if table_names:
            q = q.filter(DbTable.name.in_(table_names))
        return {r[0]: r[1] for r in q.all()}
    finally:
        db.close()
