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
import threading
import time
from typing import Dict, List, Optional

from crud.base import session_scope
from models.datasource import DataSource
from models.role import RolePermission, UserRole
from models.schema import DbColumn, DbSchema, DbTable

# ── 权限结果进程级 TTL 缓存 ─────────────────────────────────
# 权限三件套（get_visible_schema_ids / get_table_grants_by_schema /
# get_column_access_map）在单次 chat 请求内被调用 4~6 次，每次都是多表 join +
# 全表查询。用短 TTL 缓存消除同请求内的重复查询；权限变更时主动失效（立即生效）。
# TTL 短至 5 秒即可覆盖"一次请求内重复调用"的主诉求，同时将权限变更的
# 最坏生效延迟控制在 5 秒内（且有主动失效兜底，改权限即清空）。
_PERM_TTL = 5.0
_perm_cache: Dict = {}
_perm_lock = threading.Lock()


def _identity(user: dict) -> tuple:
    """用户身份指纹（含角色，is_admin 判定依赖 role/roles）"""
    return (user.get('user_id'), user.get('role'),
            tuple(sorted(user.get('roles', []) or [])))


def _cache_get(key: tuple):
    with _perm_lock:
        item = _perm_cache.get(key)
        if item is None:
            return None
        ts, val = item
        if time.time() - ts > _PERM_TTL:
            _perm_cache.pop(key, None)
            return None
        return val


def _cache_set(key: tuple, val):
    with _perm_lock:
        _perm_cache[key] = (time.time(), val)


def invalidate_permission_cache():
    """权限变更后调用，立即清空缓存"""
    with _perm_lock:
        _perm_cache.clear()


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
    """获取用户可见的 schema_id 列表。None=全部。[]=无。

    层级门控语义（数据源为总闸，库/表授权不能脱离数据源生效）：
      - datasource ALLOW(resource_id=None) → 全部数据源、全部库表可见
      - datasource ALLOW(具体 id) → 该数据源下全部库表可见
      - schema ALLOW(库) → 仅当该库所属数据源已授权时才生效；数据源未授权则库不可见
      - schema DENY(具体 id) → 强制剔除；schema DENY(resource_id=None) → 全部不可见
      - 普通用户无任何数据源/库授权 → 无可见（默认拒绝）
      - 管理员无任何授权 → 超管全可见（保留）
    """
    cache_key = ('visible_schema_ids',) + _identity(user)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with session_scope() as db:
        schema_grants = _role_grants(db, user, 'schema')
        ds_grants = _role_grants(db, user, 'datasource')
        allow = [g for g in schema_grants if g.access_type in ('ALLOW', 'SELECT')]
        allow_ds = [g for g in ds_grants if g.access_type in ('ALLOW', 'SELECT')]
        deny = {g.resource_id for g in schema_grants
                if g.access_type == 'DENY' and g.resource_id is not None}
        deny_all = any(g.resource_id is None for g in schema_grants
                       if g.access_type == 'DENY')

        all_schema_rows = {r[0]: r[1] for r in db.query(
            DbSchema.id, DbSchema.datasource_id).all()}

        # 已授权数据源集合（数据源为可见性总闸）
        ds_allow_all = any(g.resource_id is None for g in allow_ds)
        ds_allowed_ids = {g.resource_id for g in allow_ds if g.resource_id is not None}
        if ds_allow_all:
            authorized_ds = {r[0] for r in db.query(DataSource.id).all()}
        else:
            authorized_ds = ds_allowed_ids

        ds_schema_ids = {sid for sid, dsid in all_schema_rows.items()
                         if dsid in authorized_ds}
        # schema ALLOW 仅在所属数据源已授权时生效（数据源门控）
        schema_allowed = {g.resource_id for g in allow
                          if g.resource_id in all_schema_rows
                          and all_schema_rows[g.resource_id] in authorized_ds}

        if deny_all:
            result = []
        elif ds_allow_all:
            base = set(all_schema_rows.keys())
            result = list(base - deny)
        elif authorized_ds:
            base = ds_schema_ids | schema_allowed
            result = list(base - deny)
        else:
            # 数据源与库均未授权
            if is_admin(user):
                result = list(all_schema_rows.keys())   # 管理员无授权 → 超管全可见
            else:
                result = []                              # 普通用户无授权 → 无可见

    _cache_set(cache_key, result)
    return result


def is_schema_visible(user: dict, schema_name: Optional[str]) -> bool:
    """按库名校验用户可见性（None/空库名视为可）。供生成链路入口二次校验，防绕过前端。

    admin 不再整体绕过：若 admin 角色配置了 DENY，则对应库不可见。
    """
    if not schema_name:
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
    """用户配置过的表级可见集合 {schema_id: [table_id, ...]}。

    返回 {} 表示该用户对该 schema 无任何表级约束（全部可见）。
    同时处理 DENY：仅配置 DENY 的 schema 会从全表集合中减去被拒表。
    admin 同样受角色 DENY 约束（但无 ALLOW 时仍全表可见）。
    """
    cache_key = ('table_grants',) + _identity(user)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with session_scope() as db:
        rows = (db.query(DbTable.schema_id, DbTable.id, RolePermission.access_type)
            .join(RolePermission, RolePermission.resource_id == DbTable.id)
            .filter(RolePermission.role_id.in_(_role_ids(db, user)),
                RolePermission.resource_type == 'table').all())
        allow: Dict[int, set] = {}
        deny: Dict[int, set] = {}
        for schema_id, table_id, at in rows:
            if at in ('ALLOW', 'SELECT'):
                allow.setdefault(schema_id, set()).add(table_id)
            elif at == 'DENY':
                deny.setdefault(schema_id, set()).add(table_id)
        result: Dict[int, List[int]] = {}
        for schema_id, tids in allow.items():
            result[schema_id] = list(tids - deny.get(schema_id, set()))
        # 仅配置了 DENY（无 ALLOW）的 schema：全表减去被拒表
        for schema_id, dids in deny.items():
            if schema_id not in result:
                all_in_schema = {r[0] for r in db.query(DbTable.id).filter(
                    DbTable.schema_id == schema_id).all()}
                result[schema_id] = list(all_in_schema - dids)

    _cache_set(cache_key, result)
    return result


def is_table_visible(user: dict, schema_id: int, table_id: int,
                     grants_by_schema: Optional[Dict[int, List[int]]] = None) -> bool:
    """表可见性判断（单表）。admin 同样受角色 DENY 约束。"""
    if grants_by_schema is None:
        grants_by_schema = get_table_grants_by_schema(user)
    ids = grants_by_schema.get(schema_id)
    if ids is None:
        return True  # 该 schema 未配置表级约束 → 全部可见
    return table_id in ids


def filter_tables_by_permission(rows, user: dict,
                                schema_id_attr: str = 'schema_id',
                                table_id_attr: str = 'id') -> list:
    """过滤表行列表：仅保留用户可见的表（行对象需含 schema_id / id 属性）。

    admin 不再整体绕过：会按角色 DENY 剔除被拒表。
    """
    if not rows:
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

    - 非 admin：按 sensitive_level 推导默认（public/internal→SELECT, sensitive→FILTER, confidential→NONE），再用角色权限覆盖
    - admin：默认全部 SELECT（保持超管），但被角色显式 DENY/NONE 的字段降级为 NONE
    - DENY 与 NONE 视为“强制不可用”，覆盖默认与其他级别
    """
    cache_key = ('column_access',) + _identity(user) + (
        schema_name, tuple(sorted(table_names)) if table_names else None)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

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
            if is_admin(user):
                result[col_id] = 'SELECT'
            else:
                result[col_id] = _SENSITIVE_DEFAULTS.get(level or 'public', 'SELECT')

        # 角色授权覆盖：DENY/NONE 强制 NONE；其余取最高级别 SELECT > FILTER > (默认)
        role_grants = _role_grants(db, user, 'column')
        role_grants += _role_grants(db, user, 'metric')
        rank = {'NONE': 0, 'FILTER': 1, 'SELECT': 2}
        for grant in role_grants:
            rid = grant.resource_id
            if rid not in result:
                result[rid] = 'SELECT'
            at = grant.access_type
            if at in ('NONE', 'DENY'):
                result[rid] = 'NONE'
            elif at in rank:
                current = result[rid]
                if rank[at] > rank.get(current, 0):
                    result[rid] = at

    _cache_set(cache_key, result)
    return result


def filter_fields_by_permission(rows, user: dict) -> list:
    """过滤字段行：只保留用户有 SELECT 或 FILTER 权限的字段。

    用于 Schema 裁剪——LLM prompt 只注入用户可用的字段。
    SELECT 和 FILTER 级别的字段都注入（FILTER 字段可用于条件但不返回）。
    NONE 级别字段完全剔除。admin 同样受角色 DENY/NONE 约束。
    """
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
