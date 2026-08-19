# -*- coding: UTF-8 -*-
"""权限校验 — 用户通过角色继承数据与功能权限

可见性语义（对 schema 与知识一致）：
    None  = 全部可见（admin 或持有 schema_id/knowledge_id 为 NULL 的"全量"授权）
    []    = 无可见资源
    [ids] = 仅这些资源可见

字段级权限（三级）：
    SELECT  — 完全可读，可出现在 SQL 任意子句
    FILTER  — 可用不可见：允许 WHERE/JOIN/GROUP BY/HAVING，禁止 SELECT 列表
    NONE    — 完全不可用

默认行为（无显式角色字段权限时）按 sensitive_level 推导：
    public        → SELECT
    internal      → SELECT
    sensitive     → FILTER
    confidential  → NONE
"""
from typing import Optional, Dict, List

from curd.base import session_scope
from curd.role import role_permission_crud, user_role_crud
from models.schema import DbColumn, DbTable, DbSchema
from models.role import RolePermission, UserRole


def is_admin(user: dict) -> bool:
    return user.get('role') == 'admin' or 'admin' in user.get('roles', [])


def _role_ids(db, user: dict) -> list:
    return [r[0] for r in db.query(UserRole.role_id).filter(
        UserRole.user_id == user['user_id']).all()]


def _role_grants(db, user: dict, resource_type: str):
    role_ids = _role_ids(db, user)
    if not role_ids:
        return []
    return db.query(RolePermission).filter(
        RolePermission.role_id.in_(role_ids),
        RolePermission.resource_type == resource_type).all()


def has_permission(user: dict, permission_code: str,
                   resource_type: str = 'route', resource_key: Optional[str] = None) -> bool:
    """检查用户通过任一角色继承的功能权限。"""
    if is_admin(user):
        return True
    with session_scope() as db:
        query = db.query(RolePermission).filter(
            RolePermission.role_id.in_(_role_ids(db, user)),
            RolePermission.permission_code == permission_code,
            RolePermission.resource_type == resource_type,
            RolePermission.access_type.in_(['ALLOW', 'SELECT']))
        if resource_key is not None:
            query = query.filter(RolePermission.resource_key == resource_key)
        return query.first() is not None


def get_visible_schema_ids(user: dict) -> Optional[list]:
    """获取用户可见的 schema_id 列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    with session_scope() as db:
        grants = [g for g in _role_grants(db, user, 'schema')
                  if g.access_type in ('ALLOW', 'SELECT')]
        datasource_grants = [g for g in _role_grants(db, user, 'datasource')
                             if g.access_type in ('ALLOW', 'SELECT')]
        if not grants and not datasource_grants:
            return []
        if any(g.resource_id is None for g in grants + datasource_grants):
            return None
        schema_ids = {g.resource_id for g in grants}
        if datasource_grants:
            datasource_ids = {g.resource_id for g in datasource_grants}
            datasource_schema_ids = {row[0] for row in db.query(DbSchema.id).filter(
                DbSchema.datasource_id.in_(datasource_ids)).all()}
            schema_ids = schema_ids | datasource_schema_ids
        return list(schema_ids)


def is_schema_visible(user: dict, schema_name: Optional[str]) -> bool:
    """按库名校验用户可见性（None/空库名视为可）。供生成链路入口二次校验，防绕过前端。"""
    if not schema_name or is_admin(user):
        return True
    visible = get_visible_schema_ids(user)
    if visible is None:
        return True
    with session_scope() as db:
        sid = db.query(DbSchema.id).filter(DbSchema.name == schema_name).first()
    return sid is not None and sid[0] in visible


def get_visible_knowledge_ids(user: dict) -> Optional[list]:
    """获取用户可见的知识库条目 ID 列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    with session_scope() as db:
        grants = [g for g in _role_grants(db, user, 'knowledge')
                  if g.access_type in ('ALLOW', 'SELECT')]
        if not grants:
            return []
        if any(g.resource_id is None for g in grants):
            return None
        return list({g.resource_id for g in grants})


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
    with session_scope() as db:
        rows = (db.query(DbTable.schema_id, RolePermission.resource_id)
            .join(RolePermission, RolePermission.resource_id == DbTable.id)
            .filter(RolePermission.role_id.in_(_role_ids(db, user)),
                RolePermission.resource_type == 'table',
                RolePermission.access_type == 'ALLOW').all())
        result: Dict[int, List[int]] = {}
        for schema_id, table_id in rows:
            result.setdefault(schema_id, []).append(table_id)
        return result


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
    非 admin → 先按 sensitive_level 推导默认值，再用角色权限覆盖
    """
    if is_admin(user):
        return {}

    with session_scope() as db:
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

        # 多角色授权取最高访问级别：SELECT > FILTER > NONE
        role_grants = _role_grants(db, user, 'column')
        role_grants += _role_grants(db, user, 'metric')
        rank = {'NONE': 0, 'FILTER': 1, 'SELECT': 2}
        for grant in role_grants:
            if grant.resource_id in result and grant.access_type in rank:
                current = result[grant.resource_id]
                if rank[grant.access_type] > rank.get(current, 0):
                    result[grant.resource_id] = grant.access_type

        return result


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

    with session_scope() as db:
        grants = [g for g in _role_grants(db, user, 'row')
                  if g.resource_id is not None and g.filter_expression]
        if not grants:
            return {}
        table_ids = [g.resource_id for g in grants]
        # 一次 IN 查询取全部相关表名（避免 N+1）
        table_map = {t.id: t.name for t in db.query(DbTable).filter(
            DbTable.id.in_(table_ids)).all()}
        result = {}
        for grant in grants:
            name = table_map.get(grant.resource_id)
            if name and (not table_names or name in table_names):
                result[name] = grant.filter_expression
        return result
