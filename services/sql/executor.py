# -*- coding: UTF-8 -*-
"""SQL 执行器 — 将生成的 SQL 直接查询源数据库并返回结果

流程：
    1. 校验 SQL 非空、仅允许 SELECT（拒绝任何写操作）
    2. 按 schema_name 解析数据源连接（DbSchema.datasource_id → DataSource）
    3. sqlite：直接连本地库文件；其他类型：复用同步连接器构建引擎
    4. 执行并返回 {columns, rows, row_count, duration_ms, error}

安全边界：只读执行，任何非 SELECT 语句（INSERT/UPDATE/DELETE/DDL）直接拒绝。
"""
import time
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

from app.logger import logger
from app.security.crypto import decrypt_secret
from curd.base import session_scope
from models.datasource import DataSource
from models.schema import DbSchema


class SqlExecutionError(Exception):
    """SQL 执行错误（校验失败 / 连接失败 / 查询失败）"""


def _validate_select_only(sql: str) -> None:
    """校验 SQL 非空且仅允许 SELECT"""
    if not sql or not sql.strip():
        raise SqlExecutionError("SQL 为空，无法执行")
    stripped = sql.strip()
    # 只允许以 SELECT / WITH（CTE 最终也必须是 SELECT）开头
    head = stripped[:6].upper()
    if head.startswith('WITH'):
        # CTE 允许，但仍禁止包含写关键字（粗略防护，最终由网关兜底）
        upper = stripped.upper()
        for kw in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE', 'GRANT'):
            if f' {kw} ' in f' {upper} ' or upper.startswith(kw):
                raise SqlExecutionError(f"仅允许 SELECT 查询，检测到写操作关键字: {kw}")
    elif not head.startswith('SELECT'):
        raise SqlExecutionError("仅允许 SELECT 查询语句")


def _resolve_datasource(schema_name: Optional[str]) -> Optional[dict]:
    """按 schema 解析其数据源连接参数（会话内取字段，避免 detached 对象）"""
    if not schema_name:
        return None
    with session_scope() as db:
        schema = db.query(DbSchema).filter(DbSchema.name == schema_name).first()
        if not schema or not schema.datasource_id:
            return None
        ds = db.query(DataSource).filter(DataSource.id == schema.datasource_id).first()
        if not ds:
            return None
        return {
            'db_type': ds.db_type,
            'host': ds.host,
            'port': ds.port,
            'database': ds.database,
            'username': ds.username,
            'password_enc': ds.password_enc,
        }


def _build_engine_for_db_type(db_type: str, ds: dict) -> Engine:
    """按数据源连接参数构建只读执行引擎"""
    db_type = (db_type or ds.get('db_type') or 'sqlite').lower()
    password = decrypt_secret(ds.get('password_enc') or '') if ds.get('password_enc') else ''
    database = ds.get('database') or ''
    username = ds.get('username') or ''
    host = ds.get('host') or 'localhost'
    port = ds.get('port') or 0
    if db_type in ('sqlite', 'sqlite3'):
        return create_engine(
            f"sqlite:///{database or ':memory:'}",
            connect_args={'check_same_thread': False},
        )
    if db_type in ('mysql', 'mariadb', 'doris'):
        return create_engine(URL.create(
            'mysql+pymysql', username=username, password=password,
            host=host, port=port, database=database,
            query={'charset': 'utf8mb4'},
        ), pool_pre_ping=True, pool_size=1, max_overflow=2)
    if db_type in ('postgresql', 'postgres'):
        return create_engine(URL.create(
            'postgresql+psycopg2', username=username, password=password,
            host=host, port=port, database=database,
        ), pool_pre_ping=True, pool_size=1, max_overflow=2)
    raise SqlExecutionError(f"暂不支持执行该数据库类型: {db_type}")


def execute_sql(sql: str, schema_name: Optional[str] = None,
                db_type: str = 'sqlite', max_rows: int = 100) -> dict:
    """执行 SQL 查询，返回 {columns, rows, row_count, duration_ms, error}。

    Args:
        sql: 生成的 SQL（必须非空且为 SELECT）
        schema_name: 目标库名（用于定位数据源连接）
        db_type: 数据库类型（无数据源关联时的兜底）
        max_rows: 最多返回行数（防止大结果集撑爆内存）

    Raises:
        SqlExecutionError: 校验失败 / 连接失败 / 查询失败
    """
    _validate_select_only(sql)
    start = time.time()

    ds = _resolve_datasource(schema_name)
    engine = None
    try:
        if ds is not None:
            engine = _build_engine_for_db_type(db_type, ds)
        elif db_type in ('sqlite', 'sqlite3'):
            from app.config import MAIN_DB_PATH
            engine = create_engine(
                f"sqlite:///{MAIN_DB_PATH}",
                connect_args={'check_same_thread': False},
            )
        else:
            raise SqlExecutionError(
                f"未找到数据源连接（schema={schema_name}），无法执行 {db_type} 查询")

        with engine.connect() as conn:
            result = conn.execute(text(sql))
            # 列名
            col_names = list(result.keys()) if result.keys() else []
            # 取前 max_rows 行（CursorResult 迭代后需手动 limit）
            rows = []
            for i, row in enumerate(result):
                if i >= max_rows:
                    break
                rows.append([None if v is None else str(v) for v in row])
            row_count = len(rows)

        duration_ms = int((time.time() - start) * 1000)
        logger.info(f"SQL 执行完成: schema={schema_name} rows={row_count} 耗时={duration_ms}ms")
        return {
            'columns': col_names,
            'rows': rows,
            'row_count': row_count,
            'duration_ms': duration_ms,
            'error': None,
        }
    except SqlExecutionError:
        raise
    except Exception as e:
        logger.warning(f"SQL 执行失败: schema={schema_name} err={e}")
        raise SqlExecutionError(f"SQL 执行失败: {str(e)}")
    finally:
        if engine is not None:
            engine.dispose()
