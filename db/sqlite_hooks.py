# -*- coding: UTF-8 -*-
"""SQLite 专用钩子 — PRAGMA 优化与轻量迁移

仅在数据库为 SQLite 时被 engine.py 和 database.py 调用。
MySQL / PostgreSQL 不需要这些函数，也不会导入本模块的核心逻辑。
"""
from app.logger import logger


def _make_pragma(foreign_keys: bool):
    """SQLite PRAGMA 钩子 — WAL 模式 + 性能调优

    - WAL：读不阻塞写、写不阻塞读，仅写-写串行
    - busy_timeout=5000：写锁竞争时等待而非立刻失败
    - synchronous=NORMAL：WAL 下的安全性与性能平衡点
    - 主库可开启 FOREIGN KEY 约束
    """
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.execute("PRAGMA temp_store=MEMORY")
        if foreign_keys:
            cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    return _set_sqlite_pragma


def _ensure_column_sqlite(db_path: str, table: str, column: str, ddl: str) -> None:
    """轻量迁移：SQLite 已存在的表补列（幂等）

    仅用于 SQLite 本地文件的增量迁移；新数据库通过 create_all 创建全量表，
    不需要此函数。
    """
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
            if column not in cols:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
                conn.commit()
                logger.info(f"迁移: {table} 新增列 {column}")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 {table}.{column}: {e}")
