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


def _migrate_relation_cross_db(db_path: str) -> None:
    """表关系支持同数据源跨库：为 db_table_relations 补 left/right_schema_id 并重建唯一索引

    - 新增列 left_schema_id / right_schema_id（INTEGER，可空）
    - 存量行：若旧 schema_id 存在，回填 left/right = schema_id
    - 废弃单列 schema_id 置为可空（SQLite 不支持改列可空性，故整表重建一次）
    - 旧唯一索引 uix_relation_both_sides 基于单一 schema_id，重建为左右两侧 6 列复合索引
    仅用于 SQLite；幂等，可重复执行。
    """
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(db_table_relations)").fetchall()]
            if 'left_schema_id' not in cols:
                conn.execute(
                    "ALTER TABLE db_table_relations ADD COLUMN left_schema_id INTEGER")
                logger.info("迁移: db_table_relations 新增列 left_schema_id")
            if 'right_schema_id' not in cols:
                conn.execute(
                    "ALTER TABLE db_table_relations ADD COLUMN right_schema_id INTEGER")
                logger.info("迁移: db_table_relations 新增列 right_schema_id")
            # 存量行回填（旧 schema_id → 左右两侧均取该库）
            if 'schema_id' in cols:
                conn.execute(
                    "UPDATE db_table_relations "
                    "SET left_schema_id = schema_id, right_schema_id = schema_id "
                    "WHERE left_schema_id IS NULL AND schema_id IS NOT NULL")
            # 重建唯一索引（旧索引基于单一 schema_id）
            conn.execute("DROP INDEX IF EXISTS uix_relation_both_sides")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uix_relation_both_sides "
                "ON db_table_relations(left_schema_id, left_table, left_column, "
                "right_schema_id, right_table, right_column)")
            # 旧 schema_id 列 NOT NULL；SQLite 不支持 ALTER COLUMN，整表重建置可空
            if 'schema_id' in cols and _schema_id_not_null(conn):
                _rebuild_relation_table_nullable_schema_id(conn)
            conn.commit()
            logger.info("迁移: db_table_relations 跨库字段与唯一索引已就绪")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 db_table_relations 跨库字段: {e}")


def _schema_id_not_null(conn) -> bool:
    """返回 db_table_relations.schema_id 是否为 NOT NULL（pk=5 列）"""
    for r in conn.execute("PRAGMA table_info(db_table_relations)").fetchall():
        if r[1] == 'schema_id':
            return r[3] == 1  # notnull 列
    return False


def _rebuild_relation_table_nullable_schema_id(conn) -> None:
    """将 db_table_relations 的 schema_id 列改为可空（整表重建，保留数据）"""
    import sqlite3 as _sqlite3
    conn.execute("PRAGMA foreign_keys=OFF")
    cols_info = conn.execute("PRAGMA table_info(db_table_relations)").fetchall()
    col_names = [r[1] for r in cols_info]
    # 重命名旧表 → 建新表（schema_id 可空）→ 拷贝 → 删除旧表
    conn.execute("ALTER TABLE db_table_relations RENAME TO _rel_old")
    col_defs = []
    for r in cols_info:
        name, ctype, notnull, dflt, pk = r[1], r[2], r[3], r[4], r[5]
        if name == 'schema_id':
            notnull = 0  # 置可空
        ddl = f'"{name}" {ctype}'
        if notnull:
            ddl += ' NOT NULL'
        if pk:
            ddl += ' PRIMARY KEY' if pk == 1 else ''
        col_defs.append(ddl)
    conn.execute(
        f"CREATE TABLE db_table_relations ("
        f"{', '.join(col_defs)}, "
        f"UNIQUE(left_schema_id, left_table, left_column, right_schema_id, right_table, right_column))")
    placeholders = ', '.join(['?'] * len(col_names))
    rows = conn.execute(f"SELECT {', '.join(col_names)} FROM _rel_old").fetchall()
    conn.executemany(
        f"INSERT INTO db_table_relations ({', '.join(col_names)}) VALUES ({placeholders})", rows)
    conn.execute("DROP TABLE _rel_old")
    logger.info("迁移: db_table_relations.schema_id 已置为可空")


# 高频过滤/统计字段的普通索引（create_all 不会为存量表补索引，故迁移时幂等补建）
_INDEX_MIGRATIONS = [
    ('query_audit_logs', 'ix_query_audit_logs_was_blocked', 'was_blocked'),
    ('query_audit_logs', 'ix_query_audit_logs_hit_sensitive', 'hit_sensitive'),
    ('schema_change_logs', 'ix_schema_change_logs_approval_status', 'approval_status'),
    ('schema_change_logs', 'ix_schema_change_logs_change_type', 'change_type'),
    ('db_columns', 'ix_db_columns_sensitive_level', 'sensitive_level'),
    # 遥测库 llm_calls 位于独立文件，单独在 _ensure_telemetry_indexes 处理
]


def _ensure_indexes_sqlite(db_path: str) -> None:
    """SQLite 存量表补普通索引（幂等，CREATE INDEX IF NOT EXISTS）"""
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            for table, idx_name, col in _INDEX_MIGRATIONS:
                conn.execute(
                    f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                    f'ON "{table}" ("{col}")')
            conn.commit()
            logger.info("迁移: 主库普通索引已就绪")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 主库普通索引: {e}")


def _ensure_telemetry_indexes(db_path: str) -> None:
    """遥测库 llm_calls 补普通索引（status / purpose）"""
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            conn.execute(
                'CREATE INDEX IF NOT EXISTS "ix_llm_calls_status" '
                'ON "llm_calls" ("status")')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS "ix_llm_calls_purpose" '
                'ON "llm_calls" ("purpose")')
            conn.commit()
            logger.info("迁移: 遥测库普通索引已就绪")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 遥测库普通索引: {e}")
