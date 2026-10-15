# -*- coding: UTF-8 -*-
"""数据库引擎与会话工厂 — 方言自适应，支持 SQLite / MySQL / PostgreSQL

职责：根据 DATABASE_URL 自动检测方言并创建引擎，SQLite 时附加 PRAGMA 钩子，
外部数据库时使用标准连接池参数。对外暴露 engine_main / engine_telemetry /
SessionLocal / TelemetrySessionLocal / is_sqlite 标志。
"""
import re
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

import app.config as config
from app.logger import logger
from app.response import get_request_id

# ── 方言检测 ──────────────────────────────────────────────

def _is_sqlite_url(url: str) -> bool:
    return url.startswith('sqlite')


def _resolve_urls():
    """解析主库 / 遥测库 / 日志库连接 URL。

    规则（三个库一致）：
      - *_DATABASE_URL 留空 → SQLite 默认路径
      - 遥测/日志 URL 留空 + SQLite 模式 → 独立文件
      - 遥测/日志 URL 留空 + 外部数据库 → 与主库同址（表通过不同 Base 隔离）
    """
    if config.DATABASE_URL:
        main_url = config.DATABASE_URL
    else:
        main_url = f'sqlite:///{config.MAIN_DB_PATH}'

    if config.TELEMETRY_DATABASE_URL:
        telemetry_url = config.TELEMETRY_DATABASE_URL
    elif _is_sqlite_url(main_url):
        telemetry_url = f'sqlite:///{config.TELEMETRY_DB_PATH}'
    else:
        # 外部数据库：遥测表与主库同址，通过 ORM Base 类隔离
        telemetry_url = main_url

    if config.LOGS_DATABASE_URL:
        logs_url = config.LOGS_DATABASE_URL
    elif _is_sqlite_url(main_url):
        logs_url = f'sqlite:///{config.LOGS_DB_PATH}'
    else:
        # 外部数据库：日志表与主库同址，通过 ORM Base 类隔离
        logs_url = main_url

    return main_url, telemetry_url, logs_url


def _mask_url(url: str) -> str:
    """脱敏 URL 中的密码，用于日志输出"""
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', url)


# ── 引擎创建 ──────────────────────────────────────────────

def create_db_engine(db_url: str, *, foreign_keys: bool = False):
    """创建数据库引擎 — 方言自适应

    SQLite：附加 PRAGMA 钩子（WAL / busy_timeout / foreign_keys 等）
    MySQL / PostgreSQL：标准 QueuePool 连接池，pool_pre_ping 防陈旧连接
    """
    is_sqlite = _is_sqlite_url(db_url)
    pool_kwargs = dict(
        echo=config.DB_ECHO,
        poolclass=QueuePool,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        pool_timeout=config.DB_POOL_TIMEOUT,
        pool_recycle=config.DB_POOL_RECYCLE,
    )

    if is_sqlite:
        engine = create_engine(
            db_url,
            connect_args={'check_same_thread': False, 'timeout': 30},
            **pool_kwargs,
        )
        from db.sqlite_hooks import _make_pragma
        event.listen(engine, 'connect', _make_pragma(foreign_keys))
    else:
        # 外部数据库：pool_pre_ping 在取连接时做一次轻量检测，避免陈旧连接
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            **pool_kwargs,
        )

    logger.info(f"数据库引擎已创建: {_mask_url(db_url)}")
    return engine


# ── 确保数据库目录存在（仅 SQLite 模式） ───────────────────
import os

if not config.DATABASE_URL:
    for _db_path in [config.MAIN_DB_PATH, config.TELEMETRY_DB_PATH,
                     config.LOGS_DB_PATH]:
        _db_dir = os.path.dirname(_db_path)
        if _db_dir and not os.path.exists(_db_dir):
            os.makedirs(_db_dir)
            logger.info(f"创建数据库目录: {_db_dir}")

# ── 创建三库引擎 ──────────────────────────────────────────
_main_url, _telemetry_url, _logs_url = _resolve_urls()

engine_main = create_db_engine(_main_url, foreign_keys=True)
engine_telemetry = create_db_engine(_telemetry_url, foreign_keys=False)
# 日志库不开外键：三张日志表的跨库引用（users/sync_job_configs/data_sources）
# 已降级为普通索引列，由应用层级联清理保证完整性
engine_logs = create_db_engine(_logs_url, foreign_keys=False)

# 外部数据库模式下，遥测/日志引擎与主引擎相同
is_sqlite = _is_sqlite_url(_main_url)
_telemetry_same_as_main = (_telemetry_url == _main_url)
_logs_same_as_main = (_logs_url == _main_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
TelemetrySessionLocal = sessionmaker(
    autocommit=False, autoflush=False,
    bind=engine_telemetry if not _telemetry_same_as_main else engine_main,
)
LogsSessionLocal = sessionmaker(
    autocommit=False, autoflush=False,
    bind=engine_logs if not _logs_same_as_main else engine_main,
)

# ── 慢 SQL 观测（纲领 §4.1）— 只记语句文本，不记参数（防敏感值入日志） ──
_sql_start: dict = {}


@event.listens_for(engine_main, 'before_cursor_execute')
@event.listens_for(engine_telemetry, 'before_cursor_execute')
@event.listens_for(engine_logs, 'before_cursor_execute')
def _before_cursor(conn, cursor, statement, parameters, context, executemany):
    _sql_start[id(conn)] = (time.time(), statement)


@event.listens_for(engine_main, 'after_cursor_execute')
@event.listens_for(engine_telemetry, 'after_cursor_execute')
@event.listens_for(engine_logs, 'after_cursor_execute')
def _after_cursor(conn, cursor, statement, parameters, context, executemany):
    started = _sql_start.pop(id(conn), None)
    if not started:
        return
    duration_ms = (time.time() - started[0]) * 1000
    if duration_ms >= config.SLOW_SQL_MS:
        rid = get_request_id() or '-'
        logger.warning(f'[SLOW SQL] [{rid}] {duration_ms:.0f}ms {started[1][:200]}')
