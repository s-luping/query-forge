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
    conn.execute("PRAGMA foreign_keys=OFF")
    cols_info = conn.execute("PRAGMA table_info(db_table_relations)").fetchall()
    col_names = [r[1] for r in cols_info]
    # 重命名旧表 → 建新表（schema_id 可空）→ 拷贝 → 删除旧表
    conn.execute("ALTER TABLE db_table_relations RENAME TO _rel_old")
    col_defs = []
    for r in cols_info:
        name, ctype, notnull, _dflt, pk = r[1], r[2], r[3], r[4], r[5]
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
    ('db_columns', 'ix_db_columns_sensitive_level', 'sensitive_level'),
    # 日志三表已拆至日志库（logs.db），索引在 _ensure_logs_indexes 处理；
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


# 日志库（logs.db）高频过滤字段索引
_LOGS_INDEX_MIGRATIONS = [
    ('query_audit_logs', 'ix_query_audit_logs_was_blocked', 'was_blocked'),
    ('query_audit_logs', 'ix_query_audit_logs_hit_sensitive', 'hit_sensitive'),
    ('schema_change_logs', 'ix_schema_change_logs_approval_status', 'approval_status'),
    ('schema_change_logs', 'ix_schema_change_logs_change_type', 'change_type'),
]


def _ensure_logs_indexes(db_path: str) -> None:
    """日志库三表补普通索引（幂等，CREATE INDEX IF NOT EXISTS）"""
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            for table, idx_name, col in _LOGS_INDEX_MIGRATIONS:
                conn.execute(
                    f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                    f'ON "{table}" ("{col}")')
            conn.commit()
            logger.info("迁移: 日志库普通索引已就绪")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 日志库普通索引: {e}")


# 日志库三表名（存量归档迁移用；顺序：先子表后父表删，INSERT 无顺序要求）
_LOGS_TABLES = ('query_audit_logs', 'sync_run_logs', 'schema_change_logs')

# 表名 → ORM 模型（延迟 import，避免 sqlite_hooks 被 db.database 导入时成环）
_LOGS_TABLE_MODELS = {
    'query_audit_logs': ('models.security', 'QueryAuditLog'),
    'sync_run_logs': ('models.sync', 'SyncRunLog'),
    'schema_change_logs': ('models.sync', 'SchemaChangeLog'),
}


def _zero_value(col):
    """NOT NULL 无默认值列的零值（按 Python 类型）"""
    import datetime as _dt
    try:
        pt = col.type.python_type   # SQLAlchemy 中 python_type 是属性，非方法
    except Exception:
        return ''
    if pt is _dt.datetime:
        return _dt.datetime.now()
    if pt is _dt.date:
        return _dt.date.today()
    try:
        return pt()
    except Exception:
        return ''


def _coerce_value(col, value):
    """存量脏数据值转换：DateTime/Date 列接受 datetime/date 对象，
    存量库里可能是字符串（历史写入），按常见格式解析；解析不了返回 None。"""
    import datetime as _dt
    if value is None or not isinstance(value, str):
        return value
    try:
        pt = col.type.python_type   # SQLAlchemy 中 python_type 是属性，非方法
    except Exception:
        return value
    if pt is _dt.datetime:
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return _dt.datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
    if pt is _dt.date:
        try:
            return _dt.datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None
    return value


def _migrate_logs_tables(main_db_path: str, logs_db_path: str) -> None:
    """存量归档：把主库里的日志三表迁入日志库（幂等）。

    背景：日志三表原挂主库（MainBase），后拆至日志库（LogsBase）。
    对已存在的主库执行一次数据搬迁：原生 sqlite3 读主库旧表 →
    ORM 写入日志库（自动补 Python 端列默认值、显式保留 id）→
    DROP 主库旧表。迁移后主库只保留配置/元数据/业务数据。

    注意事项：
      - 必须走 ORM 而非裸 INSERT OR IGNORE：approval_status 等列只有
        Python 端默认值（SQL 层无 DEFAULT），裸插入违反 NOT NULL 会被
        IGNORE 静默跳过导致数据丢失（回归测试锁死该行为）；
      - 存量旧表可能缺新列（如 approval_status），ORM 构造时按
        __table__.columns 过滤，缺列由默认值兜底；
      - 防重入：主库不存在这些表（新库或已迁过）时直接跳过。
    """
    import importlib
    import sqlite3 as _sqlite3
    if not main_db_path or not logs_db_path:
        return

    # 1. 探测主库残留表并读出数据
    pending_data = {}
    try:
        conn = _sqlite3.connect(main_db_path)
        try:
            existing = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in _LOGS_TABLES:
                if table not in existing:
                    continue
                cols = [r[1] for r in conn.execute(
                    f'PRAGMA table_info({table})').fetchall()]
                rows = conn.execute(
                    f'SELECT {", ".join(cols)} FROM {table}').fetchall()
                pending_data[table] = (cols, rows)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 日志表归档(读取): {e}")
        return

    if not pending_data:
        logger.info("迁移: 主库无日志表需归档（新库或已迁过），跳过")
        return

    # 2. ORM 写入日志库（按传入路径建临时引擎，不依赖全局引擎状态）
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    try:
        for table, (cols, rows) in pending_data.items():
            mod_name, cls_name = _LOGS_TABLE_MODELS[table]
            model = getattr(importlib.import_module(mod_name), cls_name)
            engine = create_engine(f'sqlite:///{logs_db_path}')
            try:
                session = sessionmaker(bind=engine)()
                try:
                    for row in rows:
                        old = dict(zip(cols, row))
                        data = {}
                        for name, col in model.__table__.columns.items():
                            has_default = (col.default is not None
                                           or col.server_default is not None)
                            if name in old:
                                v = _coerce_value(col, old[name])
                                if v is None and not col.nullable and not has_default:
                                    v = _zero_value(col)
                                data[name] = v
                            elif not col.nullable and not has_default:
                                # 旧表缺列且无默认值：按 Python 类型给零值，
                                # 避免整批迁移失败（存量缺列/脏数据兜底）
                                data[name] = _zero_value(col)
                            # 其余缺列（有 default）不传键，交给 ORM 补默认值
                        session.add(model(**data))
                    session.commit()
                finally:
                    session.close()
            finally:
                engine.dispose()
            logger.info(f"迁移: {table} 已归档至日志库（{len(rows)} 行）")
    except Exception as e:
        logger.warning(f"迁移失败 日志表归档(写入): {e}")
        return

    # 3. 删除主库旧表（数据已安全落日志库后才删）
    try:
        conn = _sqlite3.connect(main_db_path)
        try:
            for table in pending_data:
                conn.execute(f'DROP TABLE {table}')
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 日志表归档(删旧表): {e}")
