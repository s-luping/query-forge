# -*- coding: UTF-8 -*-
"""数据库连接器 — 合并自 connectors/base.py + mysql.py + postgresql.py + sqlite_conn.py

新增方言：在下方 CONNECTOR_REGISTRY 注册一行，并实现 Connector 类。
"""
import json

# ── 通配符匹配（同步任务 include/exclude 表名） ─────────────
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL, Engine


def _glob_match(pattern: str, name: str) -> bool:
    """通配符匹配表名：`*` 匹配任意字符（含空），大小写不敏感。

    - 无 `*` 时退化为精确匹配（兼容旧配置的等值语义）
    - 多个 `*` 可用（如 `*SMR*_TMP`）
    """
    if not pattern:
        return False
    if '*' not in pattern:
        return pattern.lower() == name.lower()
    regex = '^' + re.escape(pattern).replace(r'\*', '.*') + '$'
    return re.match(regex, name, re.IGNORECASE) is not None


# ── 标准化元数据结构 ──────────────────────────────────────

@dataclass
class ColumnMetadata:
    """字段元数据"""
    name: str
    data_type: str = ''
    description: str = ''
    is_nullable: bool = True
    default_value: str = ''
    column_key: str = ''           # PRI / UNI / MUL
    foreign_key: str = ''           # table.column
    ordinal: int = 0


@dataclass
class TableMetadata:
    """表元数据"""
    name: str
    description: str = ''
    columns: List[ColumnMetadata] = field(default_factory=list)


# ── 连接器基类 ────────────────────────────────────────────

class BaseConnector:
    """连接器基类 — 子类实现 _build_engine() 和 read_metadata()"""

    def __init__(self, host: str = '', port: int = 0, database: str = '',
                 username: str = '', password: str = '', extra_params: str = '{}'):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.extra_params = extra_params or '{}'
        self._engine: Optional[Engine] = None

    def _build_engine(self) -> Engine:
        raise NotImplementedError

    def read_metadata(self, include_tables: Optional[List[str]] = None,
                      exclude_tables: Optional[List[str]] = None) -> List[TableMetadata]:
        raise NotImplementedError

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def test_connection(self) -> Tuple[bool, str]:
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def close(self):
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _should_include(table_name: str,
                        include_tables: Optional[List[str]] = None,
                        exclude_tables: Optional[List[str]] = None) -> bool:
        """判断表是否应纳入同步（支持 * 通配符，大小写不敏感）

        匹配规则：
          - `*SMR*`  包含匹配：表名任意位置含 SMR
          - `SMR_*`  前缀匹配：表名以 SMR_ 开头
          - `*_TMP`  后缀匹配：表名以 _TMP 结尾
          - `orders` 精确匹配：无 * 时退化为等值比较（兼容旧配置）
        """
        if exclude_tables and any(
                _glob_match(pat, table_name) for pat in exclude_tables):
            return False
        if include_tables and not any(
                _glob_match(pat, table_name) for pat in include_tables):
            return False
        return True


# ── MySQL 连接器 ──────────────────────────────────────────

class MySQLConnector(BaseConnector):
    """MySQL / MariaDB / Doris 元数据读取"""

    def _build_engine(self) -> Engine:
        url = URL.create(
            'mysql+pymysql',
            username=self.username, password=self.password,
            host=self.host, port=self.port, database=self.database,
            query={'charset': 'utf8mb4'},
        )
        return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)

    def read_metadata(self, include_tables=None, exclude_tables=None) -> List[TableMetadata]:
        engine = self._get_engine()
        sql = text("""
            SELECT t.TABLE_NAME, t.TABLE_COMMENT,
                   c.COLUMN_NAME, c.COLUMN_TYPE, c.COLUMN_COMMENT,
                   c.IS_NULLABLE, c.COLUMN_DEFAULT, c.COLUMN_KEY, c.ORDINAL_POSITION,
                   fk.REFERENCED_TABLE_NAME, fk.REFERENCED_COLUMN_NAME
            FROM information_schema.TABLES t
            JOIN information_schema.COLUMNS c
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
            LEFT JOIN information_schema.KEY_COLUMN_USAGE fk
                ON c.TABLE_SCHEMA = fk.TABLE_SCHEMA AND c.TABLE_NAME = fk.TABLE_NAME
                AND c.COLUMN_NAME = fk.COLUMN_NAME AND fk.REFERENCED_TABLE_NAME IS NOT NULL
            WHERE t.TABLE_SCHEMA = :db_name AND t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
        """)
        tables_dict: dict = {}
        seen_cols: set = set()  # (table, column) 防止一列多外键时 JOIN 行翻倍
        fk_extra: dict = {}  # (table, column) -> 追加的外键引用
        with engine.connect() as conn:
            rows = conn.execute(sql, {"db_name": self.database}).fetchall()
        for r in rows:
            table_name = r[0]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue
            col_key = (table_name, r[2])
            if col_key in seen_cols:
                # 同列多外键（源库重复声明）：合并外键引用，不重复出列
                if r[9] and r[10]:
                    fk_extra.setdefault(col_key, []).append(f"{r[9]}.{r[10]}")
                continue
            seen_cols.add(col_key)
            if table_name not in tables_dict:
                tables_dict[table_name] = TableMetadata(name=table_name, description=r[1] or '')
            col = ColumnMetadata(
                name=r[2], data_type=r[3] or '', description=r[4] or '',
                is_nullable=(r[5] != 'NO'),
                default_value=str(r[6]) if r[6] is not None else '',
                column_key=r[7] or '', ordinal=r[8] or 0,
            )
            if r[9] and r[10]:
                col.foreign_key = f"{r[9]}.{r[10]}"
            tables_dict[table_name].columns.append(col)
        for (table_name, col_name), refs in fk_extra.items():
            t = tables_dict.get(table_name)
            if not t:
                continue
            for c in t.columns:
                if c.name == col_name and refs:
                    c.foreign_key = " | ".join(filter(None, [c.foreign_key, *refs]))
                    break
        return list(tables_dict.values())


# ── PostgreSQL 连接器 ─────────────────────────────────────

class PostgreSQLConnector(BaseConnector):
    """PostgreSQL 元数据读取"""

    def _build_engine(self) -> Engine:
        url = URL.create(
            'postgresql+psycopg2',
            username=self.username, password=self.password,
            host=self.host, port=self.port, database=self.database,
        )
        return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)

    def read_metadata(self, include_tables=None, exclude_tables=None) -> List[TableMetadata]:
        engine = self._get_engine()
        sql = text("""
            SELECT c.table_name, '' AS table_comment,
                   c.column_name, c.data_type, '' AS column_comment,
                   (c.is_nullable = 'YES') AS is_nullable,
                   c.column_default, '' AS column_key, c.ordinal_position
            FROM information_schema.columns c
            JOIN information_schema.tables t
                ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE c.table_schema = :schema_name AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position
        """)
        pk_sql = text("""
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = :schema_name
        """)
        comment_sql = text("""
            SELECT c.relname AS table_name, obj_description(c.oid) AS table_comment,
                   a.attname AS column_name, col_description(c.oid, a.attnum) AS column_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = :schema_name AND c.relkind = 'r'
        """)
        schema = self.database or 'public'
        with engine.connect() as conn:
            rows = conn.execute(sql, {"schema_name": schema}).fetchall()
            pk_rows = conn.execute(pk_sql, {"schema_name": schema}).fetchall()
            comment_rows = conn.execute(comment_sql, {"schema_name": schema}).fetchall()
        pk_map: dict = {}
        for r in pk_rows:
            pk_map.setdefault(r[0], set()).add(r[1])
        col_comments: dict = {}
        table_comments: dict = {}
        for r in comment_rows:
            table_comments[r[0]] = r[1] or ''
            if r[2] and r[3]:
                col_comments[(r[0], r[2])] = r[3]
        tables_dict: dict = {}
        for r in rows:
            table_name = r[0]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue
            if table_name not in tables_dict:
                tables_dict[table_name] = TableMetadata(
                    name=table_name, description=table_comments.get(table_name, ''))
            col_name = r[2]
            tables_dict[table_name].columns.append(ColumnMetadata(
                name=col_name, data_type=r[3] or '',
                description=col_comments.get((table_name, col_name), ''),
                is_nullable=bool(r[5]),
                default_value=str(r[6]) if r[6] is not None else '',
                column_key='PRI' if col_name in pk_map.get(table_name, set()) else '',
                ordinal=r[8] or 0,
            ))
        return list(tables_dict.values())


# ── SQLite 连接器 ─────────────────────────────────────────

class SQLiteConnector(BaseConnector):
    """SQLite 元数据读取"""

    def _build_engine(self) -> Engine:
        db_path = self.database or ':memory:'
        return create_engine(f"sqlite:///{db_path}", connect_args={'check_same_thread': False})

    def read_metadata(self, include_tables=None, exclude_tables=None) -> List[TableMetadata]:
        engine = self._get_engine()
        tables: List[TableMetadata] = []
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )).fetchall()
            for (table_name,) in rows:
                if not self._should_include(table_name, include_tables, exclude_tables):
                    continue
                col_rows = conn.execute(
                    text(f"PRAGMA table_info('{table_name}')")).fetchall()
                fk_rows = conn.execute(
                    text(f"PRAGMA foreign_key_list('{table_name}')")).fetchall()
                fk_map = {r[3]: f"{r[2]}.{r[4]}" for r in fk_rows}
                tm = TableMetadata(name=table_name)
                for cr in col_rows:
                    pk_val = cr[5]
                    tm.columns.append(ColumnMetadata(
                        name=cr[1], data_type=cr[2] or '', description='',
                        is_nullable=(pk_val == 0 and cr[3] == 0),
                        default_value=str(cr[4]) if cr[4] is not None else '',
                        column_key='PRI' if pk_val > 0 else '',
                        foreign_key=fk_map.get(cr[1], ''),
                        ordinal=cr[0] or 0,
                    ))
                tables.append(tm)
        return tables


# ── Oracle 连接器 ─────────────────────────────────────────

class OracleConnector(BaseConnector):
    """Oracle 元数据读取（oracledb 瘦客户端，无需安装 Oracle Client）

    连接约定：
    - database 字段 = 服务名（service_name）；可在数据源 extra_params 中覆盖：
      {"service_name": "xxx"} 或 {"sid": "orcl"}
    - 同步范围：extra_params 指定 {"schema": "EPMDEV"} 时只同步该 Schema；
      未指定时同步登录用户 Schema，若登录用户下无表/视图，自动扩展为
      其可访问的所有业务 Schema（排除系统 Schema）
    - 同步对象：表 + 视图（视图按表元数据存储，供生成 SQL 引用）
    """

    # Oracle 系统 Schema（元数据字典等，对业务同步无意义）
    _SYSTEM_OWNERS = {
        'SYS', 'SYSTEM', 'SYSAUX', 'OUTLN', 'XDB', 'CTXSYS', 'MDSYS',
        'ORDSYS', 'ORDDATA', 'OLAPSYS', 'WMSYS', 'EXFSYS', 'DBSNMP',
        'APPQOSSYS', 'ANONYMOUS', 'XS$NULL', 'GSMADMIN_INTERNAL',
        'OJVMSYS', 'LBACSYS', 'DVSYS', 'AUDSYS', 'FLOWS_FILES',
        'DBSFWUSER', 'GGSYS', 'MDDATA', 'DIP', 'ORACLE_OCM',
        'SYS$UMF', 'SYSBACKUP', 'SYSDG', 'SYSKM', 'SYSRAC',
    }

    def _extra(self) -> dict:
        """解析 extra_params JSON（非法时静默忽略）"""
        try:
            v = json.loads(self.extra_params or '{}')
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    def _build_engine(self) -> Engine:
        try:
            import oracledb  # noqa: F401  驱动探测，未安装时报友好错误
        except ImportError:
            raise RuntimeError(
                "oracledb 驱动未安装，请在「系统管理 → 驱动管理」中安装 Oracle 驱动")
        extra = self._extra()
        query = {}
        if extra.get('service_name'):
            query['service_name'] = str(extra['service_name'])
        elif extra.get('sid'):
            query['sid'] = str(extra['sid'])
        elif self.database:
            query['service_name'] = self.database
        url = URL.create(
            'oracle+oracledb',
            username=self.username, password=self.password,
            host=self.host, port=self.port or 1521, query=query,
        )
        return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM DUAL"))
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def read_metadata(self, include_tables=None, exclude_tables=None) -> List[TableMetadata]:
        engine = self._get_engine()
        extra = self._extra()
        explicit = (extra.get('schema') or extra.get('owner') or '').strip().upper()
        owner = explicit or (self.username or '').upper()

        with engine.connect() as conn:
            tables = self._load_owners(
                conn, [owner] if owner else [], include_tables, exclude_tables)
            if not tables and not explicit:
                # 登录用户 Schema 无对象 → 同步其可访问的所有业务 Schema
                tables = self._load_owners(
                    conn, self._visible_business_owners(conn),
                    include_tables, exclude_tables)
        return tables

    def _visible_business_owners(self, conn) -> List[str]:
        """当前用户可访问的、排除系统 Schema 的所有 Schema"""
        rows = conn.execute(
            text("SELECT DISTINCT OWNER FROM ALL_TAB_COLUMNS")).fetchall()
        return [o for (o,) in rows
                if o and o not in self._SYSTEM_OWNERS
                and not re.match(r'^APEX_\d+$', o)]

    def _load_owners(self, conn, owners: List[str],
                     include_tables=None, exclude_tables=None) -> List[TableMetadata]:
        """读取指定 Schema 列表下的表/视图元数据

        以 ALL_TAB_COLUMNS 驱动（同时覆盖表和视图）；跨 Schema 同名表
        按 OWNER 排序先到先得，避免列被错误合并。
        """
        if not owners:
            return []
        owners = sorted(set(owners))
        bind = lambda sql: sql.bindparams(bindparam('owners', expanding=True))  # noqa: E731
        col_sql = bind(text("""
            SELECT c.OWNER, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
                   c.DATA_LENGTH, c.DATA_PRECISION, c.DATA_SCALE,
                   c.NULLABLE, c.DATA_DEFAULT, c.COLUMN_ID
            FROM ALL_TAB_COLUMNS c
            WHERE c.OWNER IN :owners
            ORDER BY c.OWNER, c.TABLE_NAME, c.COLUMN_ID
        """))
        tab_comment_sql = bind(text("""
            SELECT OWNER, TABLE_NAME, COMMENTS FROM ALL_TAB_COMMENTS
            WHERE OWNER IN :owners AND TABLE_TYPE IN ('TABLE', 'VIEW')
        """))
        pk_sql = bind(text("""
            SELECT cc.OWNER, cc.TABLE_NAME, cc.COLUMN_NAME
            FROM ALL_CONSTRAINTS cst
            JOIN ALL_CONS_COLUMNS cc
                ON cc.OWNER = cst.OWNER AND cc.CONSTRAINT_NAME = cst.CONSTRAINT_NAME
            WHERE cst.CONSTRAINT_TYPE = 'P' AND cc.OWNER IN :owners
        """))
        fk_sql = bind(text("""
            SELECT fc.OWNER, fc.TABLE_NAME, fcc.COLUMN_NAME,
                   pc.TABLE_NAME AS REF_TABLE, rcc.COLUMN_NAME AS REF_COL
            FROM ALL_CONSTRAINTS fc
            JOIN ALL_CONS_COLUMNS fcc
                ON fcc.OWNER = fc.OWNER AND fcc.CONSTRAINT_NAME = fc.CONSTRAINT_NAME
            JOIN ALL_CONSTRAINTS pc
                ON pc.OWNER = fc.R_OWNER AND pc.CONSTRAINT_NAME = fc.R_CONSTRAINT_NAME
            JOIN ALL_CONS_COLUMNS rcc
                ON rcc.OWNER = pc.OWNER AND rcc.CONSTRAINT_NAME = pc.CONSTRAINT_NAME
                AND rcc.POSITION = fcc.POSITION
            WHERE fc.CONSTRAINT_TYPE = 'R' AND fc.OWNER IN :owners
        """))
        col_comment_sql = bind(text("""
            SELECT OWNER, TABLE_NAME, COLUMN_NAME, COMMENTS FROM ALL_COL_COMMENTS
            WHERE OWNER IN :owners
        """))

        col_rows = conn.execute(col_sql, {"owners": owners}).fetchall()
        tab_comments: dict = {}
        for r in conn.execute(tab_comment_sql, {"owners": owners}).fetchall():
            tab_comments.setdefault(r[1], r[2] or '')
        pk_map: dict = {}
        for r in conn.execute(pk_sql, {"owners": owners}).fetchall():
            pk_map.setdefault(r[1], set()).add(r[2])
        fk_map: dict = {}
        for r in conn.execute(fk_sql, {"owners": owners}).fetchall():
            fk_map.setdefault((r[1], r[2]), f"{r[3]}.{r[4]}")
        col_comments: dict = {}
        for r in conn.execute(col_comment_sql, {"owners": owners}).fetchall():
            if r[3]:
                col_comments.setdefault((r[1], r[2]), r[3])

        tables_dict: dict = {}
        owner_of_table: dict = {}
        for r in col_rows:
            r_owner, table_name, col_name = r[0], r[1], r[2]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue
            if owner_of_table.setdefault(table_name, r_owner) != r_owner:
                # 同名表已被其他 Schema 占用（按 OWNER 排序先到先得），跳过
                continue
            if table_name not in tables_dict:
                tables_dict[table_name] = TableMetadata(
                    name=table_name, description=tab_comments.get(table_name, ''))
            tables_dict[table_name].columns.append(ColumnMetadata(
                name=col_name, data_type=self._format_type(r[3], r[4], r[5], r[6]),
                description=col_comments.get((table_name, col_name), ''),
                is_nullable=(r[7] != 'N'),
                default_value=str(r[8]) if r[8] is not None else '',
                column_key='PRI' if col_name in pk_map.get(table_name, set()) else '',
                foreign_key=fk_map.get((table_name, col_name), ''),
                ordinal=r[9] or 0,
            ))
        return list(tables_dict.values())

    @staticmethod
    def _format_type(data_type, data_length, data_precision, data_scale) -> str:
        """拼接可读类型：VARCHAR2(128) / NUMBER(10,2) / DATE"""
        data_type = (data_type or '').upper()
        if data_type in ('NUMBER', 'DECIMAL', 'NUMERIC'):
            if data_precision is not None:
                if data_scale:
                    return f"{data_type}({data_precision},{data_scale})"
                return f"{data_type}({data_precision})"
            return data_type
        if data_type in ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'RAW'):
            return f"{data_type}({data_length})" if data_length else data_type
        return data_type


# ── 注册表 ─────────────────────────────────────────────────

CONNECTOR_REGISTRY = {
    'mysql': MySQLConnector,
    'mariadb': MySQLConnector,
    'doris': MySQLConnector,
    'postgresql': PostgreSQLConnector,
    'postgres': PostgreSQLConnector,
    'sqlite': SQLiteConnector,
    'sqlite3': SQLiteConnector,
    'oracle': OracleConnector,
}

PENDING_DB_TYPES = {'sqlserver', 'hive', 'clickhouse'}


def get_connector(db_type: str, **conn_kwargs) -> BaseConnector:
    """获取连接器实例"""
    db_type = (db_type or 'mysql').lower()
    cls = CONNECTOR_REGISTRY.get(db_type)
    if cls is None:
        if db_type in PENDING_DB_TYPES:
            raise ValueError(
                f"数据库类型 {db_type} 的连接器尚未实现（驱动已支持安装，同步功能开发中）")
        raise ValueError(f"不支持的数据库类型: {db_type}，支持: {list(CONNECTOR_REGISTRY.keys())}")
    return cls(**conn_kwargs)


__all__ = ['BaseConnector', 'TableMetadata', 'ColumnMetadata',
           'CONNECTOR_REGISTRY', 'get_connector',
           'MySQLConnector', 'PostgreSQLConnector', 'SQLiteConnector',
           'OracleConnector']
