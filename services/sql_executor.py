# -*- coding: UTF-8 -*-
"""SQL 执行器 — 将生成的 SQL 直接查询源数据库并返回结果

流程：
    1. 校验 SQL 非空、仅允许 SELECT（拒绝任何写操作）
    2. 按 schema_name 解析数据源连接（DbSchema.datasource_id → DataSource）
    3. sqlite：直接连本地库文件；其他类型：复用同步连接器构建引擎
    4. 执行并返回 {columns, rows, row_count, duration_ms, error}

安全边界：只读执行，任何非 SELECT 语句（INSERT/UPDATE/DELETE/DDL）直接拒绝。
"""
import threading
import time
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from app.crypto import decrypt_secret
from app.logger import logger
from crud.base import session_scope
from models.datasource import DataSource
from models.schema import DbSchema


class SqlExecutionError(Exception):
    """SQL 执行错误（校验失败 / 连接失败 / 查询失败）"""


# ── 数据源引擎缓存 ──────────────────────────────────────────
# 每次查询都 create_engine + dispose 会导致连接池反复建连/销毁，
# MySQL/PostgreSQL 数据源在并发下连接开销大、源库压力高。
# 按数据源 id 缓存 Engine，连接指纹变化（改密码/改库）时自动重建。
_engine_cache: dict = {}          # {datasource_id: (fingerprint, Engine)}
_engine_lock = threading.Lock()


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
            'id': ds.id,
            'db_type': ds.db_type,
            'host': ds.host,
            'port': ds.port,
            'database': ds.database,
            'username': ds.username,
            'password_enc': ds.password_enc,
        }


_SQLGLOT_DIALECT = {
    'sqlite': 'sqlite', 'mysql': 'mysql', 'postgresql': 'postgres',
    'postgres': 'postgres', 'oracle': 'oracle', 'sqlserver': 'tsql', 'mssql': 'tsql',
}


def _extract_sql_schema_names(sql: str, db_type: str = '') -> List[str]:
    """从 SQL 中提取表引用携带的库名（库名.表名 形式），去重保序。

    跨库模式（schema_name=None）下生成的 SQL 会带库前缀（如 pjmall.asset），
    执行前据此路由到正确数据源连接；无库前缀的 SQL 返回空列表（走默认路径）。
    解析失败不阻断主流程（静默返回空，交由原逻辑兜底）。
    """
    names: List[str] = []
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, dialect=_SQLGLOT_DIALECT.get((db_type or '').lower()))
        for t in tree.find_all(exp.Table):
            if t.db and t.db not in names:
                names.append(t.db)
    except Exception:
        pass
    # 解析仍失败时正则兜底：只匹配 FROM/JOIN/UPDATE/INTO 后的 库名.表名，
    # 兼容反引号/双引号/方括号/裸写四种引用风格（避免别名.列名误判）
    if not names:
        import re
        for m in re.finditer(
            r'(?:FROM|JOIN|UPDATE|INTO)\s+'
            r'((?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)\.'
            r'(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*))',
            sql, re.IGNORECASE):
            schema = m.group(1).split('.')[0].strip('`"[]')
            if schema not in names:
                names.append(schema)
    return names


def _build_engine_for_db_type(db_type: str, ds: dict) -> Engine:
    """按数据源连接参数构建只读执行引擎

    数据源自身类型优先（跨库模式下调用方兜底类型可能与实际库类型不一致）。
    """
    db_type = (ds.get('db_type') or db_type or 'sqlite').lower()
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


def _get_cached_engine(ds: dict, db_type: str) -> Engine:
    """按数据源缓存引擎；连接指纹变化（改密码/改库等）时重建。

    指纹不含明文密码（用 password_enc 密文代表），改密码后指纹变化即触发重建，
    旧引擎对象待引用归零后由 GC 回收，不主动 dispose（可能仍有请求在用）。
    """
    ds_id = ds.get('id')
    fingerprint = (
        ds.get('db_type') or db_type,
        ds.get('host'), ds.get('port'), ds.get('database'),
        ds.get('username'), ds.get('password_enc'),
    )
    if ds_id is None:
        # 无 id（理论不出现，防御）：不缓存，直接构建
        return _build_engine_for_db_type(db_type, ds)

    with _engine_lock:
        cached = _engine_cache.get(ds_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        engine = _build_engine_for_db_type(db_type, ds)
        _engine_cache[ds_id] = (fingerprint, engine)
        return engine


def _max_rows_config() -> int:
    """查询结果行数上限：读系统设置 SQL_MAX_ROWS，缺省 2000。

    前端气泡预览 10 行、结果弹窗 50 行/页分页，渲染成本与总行数无关；
    2000 行 JSON 约 0.5~1MB，传输与存储均可接受（基准评测覆盖 99%+ 题目）。
    """
    try:
        from db import get_setting
        v = str(get_setting('SQL_MAX_ROWS', '') or '').strip()
        if v.isdigit() and int(v) > 0:
            return int(v)
    except Exception:
        pass
    return 2000


def execute_sql(sql: str, schema_name: Optional[str] = None,
                db_type: str = 'sqlite', max_rows: Optional[int] = None) -> dict:
    """执行 SQL 查询，返回 {columns, rows, row_count, duration_ms, error}。

    Args:
        sql: 生成的 SQL（必须非空且为 SELECT）
        schema_name: 目标库名（用于定位数据源连接）
        db_type: 数据库类型（无数据源关联时的兜底）
        max_rows: 最多返回行数（防大结果集撑爆内存）；None 时读系统设置 SQL_MAX_ROWS（默认 2000）

    Raises:
        SqlExecutionError: 校验失败 / 连接失败 / 查询失败
    """
    _validate_select_only(sql)
    if max_rows is None:
        max_rows = _max_rows_config()
    start = time.time()

    # 跨库模式（schema_name=None）：从 SQL 表前缀解析目标库，路由到对应数据源
    # 例如「pjmall.asset JOIN sys.sys_config」→ 优先用 SQL 中第一个库的数据源连接
    resolved_schema = schema_name
    if not schema_name:
        sql_schemas = _extract_sql_schema_names(sql, db_type)
        if sql_schemas:
            resolved_schema = sql_schemas[0]

    ds = _resolve_datasource(resolved_schema)
    try:
        if ds is not None:
            # 数据源类型优先于调用方兜底类型（跨库场景尤为重要）
            engine = _get_cached_engine(ds, db_type)
        elif db_type in ('sqlite', 'sqlite3'):
            from db import engine_main
            engine = engine_main
        else:
            raise SqlExecutionError(
                f"未找到数据源连接（schema={resolved_schema}），无法执行 {db_type} 查询")

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
        logger.info(f"SQL 执行完成: schema={resolved_schema} rows={row_count} 耗时={duration_ms}ms")
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
        logger.warning(f"SQL 执行失败: schema={resolved_schema} err={e}")
        raise SqlExecutionError(f"SQL 执行失败: {str(e)}")
