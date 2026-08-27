"""SQL 权限网关 — AST 解析 + 字段权限校验 + SELECT* 展开 + 行级过滤注入

使用 sqlglot 解析 SQL AST，提取表/字段及其子句上下文，
按用户字段级权限（SELECT/FILTER/NONE）校验并改写 SQL。

典型用法：
    gateway = SqlGateway(user)
    result = gateway.process(sql, schema_name='my_schema', db_type='mysql')
    if not result['is_allowed']:
        raise PermissionDenied(result['block_reason'])
    safe_sql = result['sql']
"""
import logging
from typing import Dict, List, Optional, Tuple

import sqlglot
from sqlglot import exp

from models.schema import DbColumn, DbTable, DbSchema
from crud.base import session_scope
from app.permissions import (is_admin, get_column_access_map, get_row_scope_rules,
                             get_table_grants_by_schema)

logger = logging.getLogger(__name__)

_DIALECT_MAP = {
    'sqlite': 'sqlite',
    'mysql': 'mysql',
    'postgresql': 'postgres',
    'postgres': 'postgres',
    'oracle': 'oracle',
    'sqlserver': 'tsql',
    'mssql': 'tsql',
}


class SqlGatewayResult:
    """网关处理结果"""
    __slots__ = ('sql', 'is_allowed', 'block_reason', 'tables', 'columns',
                 'hit_sensitive', 'was_modified', 'modifications')

    def __init__(self):
        self.sql = ''
        self.is_allowed = True
        self.block_reason = ''
        self.tables: List[str] = []
        self.columns: Dict[str, str] = {}  # {column_name: clause_context}
        self.hit_sensitive = False
        self.was_modified = False
        self.modifications: List[str] = []

    def to_dict(self) -> dict:
        return {
            'sql': self.sql,
            'is_allowed': self.is_allowed,
            'block_reason': self.block_reason,
            'tables': self.tables,
            'columns': self.columns,
            'hit_sensitive': self.hit_sensitive,
            'was_modified': self.was_modified,
            'modifications': self.modifications,
        }


class SqlGateway:
    """SQL 权限网关"""

    def __init__(self, user: dict):
        self.user = user
        self._is_admin = is_admin(user)
        self._access_map: Dict[int, str] = {}  # {column_id: SELECT/FILTER/NONE}
        self._row_scopes: Dict[str, str] = {}  # {table_name: filter_expression}
        # 跨库支持：key 统一为 (db_name or '', table_name)
        self._col_lookup: Dict[Tuple[str, str, str], Tuple[int, str]] = {}  # {(db, table, col): (col_id, sensitive)}
        self._table_schema: Dict[Tuple[str, str], int] = {}  # {(db, table): schema_id}
        self._table_grants_by_name: Dict[int, set] = {}  # {schema_id: {table_name,...}} 表级白名单(表名)

    def process(self, sql: str, schema_name: Optional[str] = None,
                db_type: str = 'sqlite') -> SqlGatewayResult:
        """处理 SQL：解析 → 校验 → 改写"""
        result = SqlGatewayResult()
        result.sql = sql

        # 不再为 admin 整体跳过校验：admin 同样受角色 DENY（schema/table/column）约束，
        # 路由层 is_schema_visible 已先行拦截被拒库，这里做 SQL 级兜底（表/字段级）。
        # 仅保留解析表/字段用于审计信息。
        try:
            tree = sqlglot.parse_one(sql, dialect=_DIALECT_MAP.get(db_type, 'sqlite'))
            result.tables = self._extract_tables(tree)
            result.columns = self._extract_columns_with_context(tree)
        except Exception:
            pass

        dialect = _DIALECT_MAP.get(db_type, 'sqlite')

        # 1. 解析 SQL
        try:
            tree = sqlglot.parse_one(sql, dialect=dialect)
        except Exception as e:
            result.is_allowed = False
            result.block_reason = f'SQL 解析失败: {e}'
            return result

        # 2. 提取表名
        result.tables = self._extract_tables(tree)

        # 3. 加载权限数据
        self._load_permissions(schema_name, result.tables)

        # 4. 提取字段及其子句上下文
        result.columns = self._extract_columns_with_context(tree)

        # 4.5 校验表级权限（库内白名单外的表直接拦截）
        blocked = self._check_table_permissions(tree, result)
        if blocked:
            return result

        # 5. 校验字段权限
        blocked = self._check_permissions(tree, result)
        if blocked:
            return result

        # 6. 展开 SELECT *
        self._expand_select_star(tree, result)

        # 7. 注入行级过滤
        tree = self._inject_row_scope(tree, result, dialect=dialect)

        # 8. 生成最终 SQL
        if result.was_modified:
            result.sql = tree.sql(dialect=dialect)
        else:
            result.sql = sql

        return result

    def _extract_tables(self, tree: exp.Expression) -> List[str]:
        """提取 SQL 中引用的所有表名（跨库场景返回 库名.表名 或 表名）"""
        tables = []
        for t in tree.find_all(exp.Table):
            # 带库前缀时返回 库名.表名（权限校验/审计用精确标识）
            name = f"{t.db}.{t.name}" if t.db else t.name
            if name and name not in tables:
                tables.append(name)
        return tables

    def _extract_columns_with_context(self, tree: exp.Expression) -> Dict[str, str]:
        """提取字段及其所在子句上下文"""
        col_context = {}

        for col in tree.find_all(exp.Column):
            col_name = col.name
            if not col_name:
                continue

            # 判断字段所在子句
            clause = self._get_clause_context(col)
            existing = col_context.get(col_name, '')
            if clause not in existing:
                col_context[col_name] = f'{existing},{clause}' if existing else clause

        return col_context

    def _get_clause_context(self, col: exp.Column) -> str:
        """判断字段所在的 SQL 子句"""
        parent = col.parent
        while parent is not None:
            if isinstance(parent, exp.Where):
                return 'WHERE'
            elif isinstance(parent, exp.Join):
                return 'JOIN'
            elif isinstance(parent, exp.Group):
                return 'GROUP_BY'
            elif isinstance(parent, exp.Having):
                return 'HAVING'
            elif isinstance(parent, exp.Order):
                return 'ORDER_BY'
            elif isinstance(parent, exp.Select):
                return 'SELECT'
            parent = parent.parent
        return 'UNKNOWN'

    def _load_permissions(self, schema_name: Optional[str], table_names: List[str]):
        """加载字段权限、行级规则与表级白名单（跨库支持：schema_name=None 时全库）"""
        # 提取纯表名（去掉库前缀）用于权限查询
        pure_names = [t.split('.', 1)[1] if '.' in t else t for t in table_names] or None
        self._access_map = get_column_access_map(self.user, schema_name=schema_name,
                                                  table_names=pure_names)
        self._row_scopes = get_row_scope_rules(self.user, table_names=pure_names)

        # 构建 (db, table, col) → (column_id, sensitive_level) 查找表
        with session_scope() as db:
            q = (db.query(DbSchema.name, DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                          DbTable.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id))
            if schema_name:
                q = q.filter(DbSchema.name == schema_name)
            if pure_names:
                q = q.filter(DbTable.name.in_(pure_names))
            for db_name, col_id, col_name, sensitive, tbl_name in q.all():
                self._col_lookup[(db_name or '', tbl_name, col_name)] = (
                    col_id, sensitive or 'public')

            # (db, table) → schema_id 映射（表级权限判定用）
            tq = (db.query(DbSchema.name, DbTable.name, DbTable.schema_id)
                  .join(DbSchema, DbTable.schema_id == DbSchema.id))
            if schema_name:
                tq = tq.filter(DbSchema.name == schema_name)
            if pure_names:
                tq = tq.filter(DbTable.name.in_(pure_names))
            for db_name, name, sid in tq.all():
                self._table_schema[(db_name or '', name)] = sid

            # 表级白名单 {schema_id: {table_name,...}}（表名形式便于 SQL 表名校验）
            grants = get_table_grants_by_schema(self.user)
            if grants:
                grant_ids = [tid for tids in grants.values() for tid in tids]
                if grant_ids:
                    for name, sid in db.query(DbTable.name, DbTable.schema_id).filter(
                            DbTable.id.in_(grant_ids)).all():
                        self._table_grants_by_name.setdefault(sid, set()).add(name)
    def _check_table_permissions(self, tree: exp.Expression, result: SqlGatewayResult) -> bool:
        """校验表级权限：受限 schema 中白名单外的表 → 拦截。返回 True 表示被拦截"""
        if not self._table_grants_by_name:
            return False
        for t in tree.find_all(exp.Table):
            db_name, tname = t.db or '', t.name
            if not tname:
                continue
            sid = self._table_schema.get((db_name, tname))
            if sid is None:
                continue  # 未知表（不存在）→ 交由数据库报错
            allowed = self._table_grants_by_name.get(sid)
            if allowed is not None and tname not in allowed:
                result.is_allowed = False
                result.block_reason = f'无权访问表 {tname}'
                return True
        return False

    def _check_permissions(self, tree: exp.Expression, result: SqlGatewayResult) -> bool:
        """校验字段权限，返回 True 表示被拦截"""
        for col in tree.find_all(exp.Column):
            col_name = col.name
            if not col_name:
                continue

            # 解析表名（处理别名）+ 库名
            table_name, db_name = self._resolve_table_name(col)
            clause = self._get_clause_context(col)

            # 查找 column_id 和权限（跨库 key：db + table + col）
            lookup_key = (db_name or '', table_name, col_name)
            col_info = self._col_lookup.get(lookup_key)

            # 兼容无库前缀 SQL：同表名在多库时取第一个匹配（旧行为兜底）
            if col_info is None and db_name:
                col_info = self._col_lookup.get(('', table_name, col_name))

            if col_info is None:
                # 字段不在已知 schema 中，可能是不存在的字段，跳过（让 DB 报错）
                continue

            col_id, sensitive_level = col_info
            access = self._access_map.get(col_id, 'NONE')

            # 检查敏感字段
            if sensitive_level in ('sensitive', 'confidential'):
                result.hit_sensitive = True

            # 权限校验
            if access == 'NONE':
                result.is_allowed = False
                result.block_reason = f'无权访问字段 {table_name}.{col_name}'
                return True

            if access == 'FILTER' and clause == 'SELECT':
                result.is_allowed = False
                result.block_reason = (f'字段 {table_name}.{col_name} 仅可用于条件过滤，'
                                       f'不允许出现在 SELECT 列表中')
                return True

        return False

    def _resolve_table_name(self, col: exp.Column) -> Tuple[str, str]:
        """解析字段引用的表名（处理别名），返回 (table_name, db_name)"""
        table = col.table
        if table:
            # 尝试在查询中找该别名对应的真实表（取 db）
            select = col.find_ancestor(exp.Select)
            if select:
                for t in select.find_all(exp.Table):
                    if t.alias_or_name == table:
                        return t.name, (t.db or '')
            return table, ''
        # 如果没有表前缀，尝试从 FROM 子句推断
        select = col.find_ancestor(exp.Select)
        if select:
            for t in select.find_all(exp.Table):
                return t.name, (t.db or '')
        return '', ''

    def _expand_select_star(self, tree: exp.Expression, result: SqlGatewayResult):
        """展开 SELECT * 为授权字段列表"""
        for star in tree.find_all(exp.Star):
            select = star.find_ancestor(exp.Select)
            if not select:
                continue

            # 获取 SELECT 涉及的表（带库名，避免跨库同名表混淆）
            tables_in_select = set()
            for t in select.find_all(exp.Table):
                tables_in_select.add((t.db or '', t.name))

            if not tables_in_select:
                continue

            # 获取授权字段
            authorized_cols = self._get_authorized_columns(list(tables_in_select))
            if not authorized_cols:
                continue

            # 构建 SELECT 列表
            new_expressions = []
            for (db_name, table_name), col_names in authorized_cols.items():
                for col_name in col_names:
                    col = exp.column(col_name, table=table_name)
                    if db_name:
                        col.set('db', exp.Identifier(this=db_name))
                    new_expressions.append(col)

            if new_expressions:
                # 替换 SELECT * 中的 *
                select.set('expressions', new_expressions)
                result.was_modified = True
                result.modifications.append(f'展开 SELECT * 为 {len(new_expressions)} 个授权字段')
                # 不 break — 继续处理后续 SELECT *（多表 JOIN 场景）

    def _get_authorized_columns(self, table_keys: List[Tuple[str, str]]) -> Dict[Tuple[str, str], List[str]]:
        """获取表的授权字段列表（SELECT 级别）。table_keys: [(db_name, table_name), ...]"""
        pure_names = [t for _db, t in table_keys]
        with session_scope() as db:
            q = (db.query(DbSchema.name, DbColumn.name, DbColumn.id, DbTable.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id)
                 .filter(DbTable.name.in_(pure_names)))
            result: Dict[Tuple[str, str], List[str]] = {}
            for db_name, col_name, col_id, tbl_name in q.all():
                access = self._access_map.get(col_id, 'NONE')
                if access == 'SELECT':
                    result.setdefault((db_name or '', tbl_name), []).append(col_name)
            return result

    def _inject_row_scope(self, tree: exp.Expression, result: SqlGatewayResult,
                          dialect: str = 'sqlite') -> exp.Expression:
        """注入行级过滤条件，返回修改后的 tree"""
        if not self._row_scopes:
            return tree

        tables_in_sql = set(self._extract_tables(tree))

        for table_name, filter_expr in self._row_scopes.items():
            if table_name in tables_in_sql:
                try:
                    tree = tree.where(filter_expr, append=True, dialect=dialect)
                    result.was_modified = True
                    result.modifications.append(f'注入行级过滤: {table_name} → {filter_expr}')
                except Exception:
                    logger.warning(f'行级过滤表达式注入失败: {filter_expr}')

        return tree
