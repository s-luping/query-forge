# -*- coding: UTF-8 -*-
"""数据库连接器 — 合并自 connectors/base.py + mysql.py + postgresql.py + sqlite_conn.py

新增方言：在下方 CONNECTOR_REGISTRY 注册一行，并实现 Connector 类。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.engine import Engine


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
        if exclude_tables and table_name.lower() in [t.lower() for t in exclude_tables]:
            return False
        if include_tables and table_name.lower() not in [t.lower() for t in include_tables]:
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
        with engine.connect() as conn:
            rows = conn.execute(sql, {"db_name": self.database}).fetchall()
        for r in rows:
            table_name = r[0]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue
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


# ── 注册表 ─────────────────────────────────────────────────

CONNECTOR_REGISTRY = {
    'mysql': MySQLConnector,
    'mariadb': MySQLConnector,
    'doris': MySQLConnector,
    'postgresql': PostgreSQLConnector,
    'postgres': PostgreSQLConnector,
    'sqlite': SQLiteConnector,
    'sqlite3': SQLiteConnector,
}

PENDING_DB_TYPES = {'sqlserver', 'oracle', 'hive', 'clickhouse'}


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
           'MySQLConnector', 'PostgreSQLConnector', 'SQLiteConnector']
