# -*- coding: UTF-8 -*-
"""日志库拆分回归 — 日志三表从主库拆至 logs.db（LogsBase）

锁定性质：
    1. 模型归属：QueryAuditLog / SyncRunLog / SchemaChangeLog 挂 LogsBase，
       且跨库引用（user_id / job_id / datasource_id）已降级为普通列；
    2. 会话绑定：session_scope(logs=True) 绑到日志引擎，tx_scope 同理；
    3. 存量归档：_migrate_logs_tables 幂等搬迁（数据不丢、可重复执行、
       迁后主库无残留表）；
    4. 互斥校验：telemetry 与 logs 同时为 True 必须报错。
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.sqlite_hooks import _migrate_logs_tables  # noqa: E402


def _all_models():
    import importlib
    for mod in ('user', 'role', 'schema', 'knowledge', 'conversation', 'llm',
                'system', 'vector_index', 'security', 'sync', 'datasource'):
        importlib.import_module(f'models.{mod}')


def test_log_tables_belong_to_logs_base():
    """三张日志表必须挂 LogsBase，不在 MainBase"""
    _all_models()
    from models.base import LogsBase, MainBase
    from models.security import QueryAuditLog
    from models.sync import SchemaChangeLog, SyncRunLog

    for model in (QueryAuditLog, SyncRunLog, SchemaChangeLog):
        assert model.__base__ is LogsBase, (
            f'{model.__name__} 应挂 LogsBase')
        assert model.__tablename__ not in MainBase.metadata.tables, (
            f'{model.__tablename__} 不应仍在主库 metadata')

    assert set(LogsBase.metadata.tables) == {
        'query_audit_logs', 'sync_run_logs', 'schema_change_logs'}


def test_cross_db_fk_downgraded_to_plain_column():
    """跨库引用不得再是 ForeignKey（SQLite 跨文件无外键），
    库内引用（schema_change_logs.run_log_id → sync_run_logs.id）保留外键"""
    _all_models()
    from models.security import QueryAuditLog
    from models.sync import SchemaChangeLog, SyncRunLog

    def fk_targets(model):
        out = []
        for col in model.__table__.columns:
            for fk in col.foreign_keys:
                out.append(fk.target_fullname)
        return out

    assert fk_targets(QueryAuditLog) == [], 'query_audit_logs 不应有外键'
    assert fk_targets(SyncRunLog) == [], 'sync_run_logs 不应有外键'
    # run_log_id 保留库内外键；job_id / datasource_id 已降级
    assert fk_targets(SchemaChangeLog) == ['sync_run_logs.id']


def test_session_scope_binds_logs_engine():
    """session_scope(logs=True) 必须绑日志引擎（独立文件时不同于主库）"""
    from crud.base import session_scope, tx_scope
    from db.engine import engine_logs, engine_main

    if engine_logs is engine_main:
        import pytest
        pytest.skip('外部数据库模式下日志库与主库同址，无独立引擎可断言')

    with session_scope(logs=True) as db:
        assert db.bind is engine_logs
    with tx_scope(logs=True) as db:
        assert db.bind is engine_logs
    with session_scope() as db:
        assert db.bind is engine_main


def test_telemetry_and_logs_mutually_exclusive():
    """telemetry 与 logs 互斥，防误绑定"""
    import pytest

    from crud.base import session_scope

    with pytest.raises(ValueError):
        with session_scope(telemetry=True, logs=True):
            pass


def test_migrate_logs_tables_handles_legacy_datetime_strings(tmp_path):
    """存量脏数据回归：旧表 DateTime 列存的是字符串（历史写入方式），
    ORM 迁移必须解析为 datetime，否则整批 INSERT 报
    'SQLite DateTime type only accepts Python datetime and date objects'，
    且主库旧表已被 DROP → 数据丢失。该场景由端到端验证（副本库）抓到。"""
    main_db = tmp_path / 'legacy.db'
    logs_db = tmp_path / 'logs.db'

    conn = sqlite3.connect(main_db)
    conn.executescript("""
        CREATE TABLE query_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            username TEXT, query TEXT NOT NULL, created_at TEXT);
        INSERT INTO query_audit_logs (user_id, username, query, created_at)
            VALUES (1, 'admin', '老数据', '2026-08-20 10:30:00.123456'),
                   (2, 'user', '带秒无微秒', '2026-08-21 09:00:00'),
                   (3, 'user', '日期 only', '2026-08-22'),
                   (4, 'user', 'ISO T', '2026-08-23T08:00:00');
        CREATE TABLE sync_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
            status TEXT, started_at TEXT);
        INSERT INTO sync_run_logs (job_id, status, started_at)
            VALUES (1, 'success', '2026-08-20 11:00:00');
        CREATE TABLE schema_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_log_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL, datasource_id INTEGER NOT NULL,
            target_schema_name TEXT, change_type TEXT, object_type TEXT,
            object_name TEXT, created_at TEXT);
        INSERT INTO schema_change_logs
            (run_log_id, job_id, datasource_id, target_schema_name,
             change_type, object_type, object_name, created_at)
            VALUES (1, 1, 1, 'mydb', 'add', 'table', 't1', '2026-08-20 12:00:00');
    """)
    conn.commit()
    conn.close()

    _all_models()
    from sqlalchemy import create_engine

    from models.base import LogsBase
    LogsBase.metadata.create_all(create_engine(f'sqlite:///{logs_db}'))

    _migrate_logs_tables(str(main_db), str(logs_db))

    # 四行全部迁入（一行不丢）
    conn = sqlite3.connect(logs_db)
    assert conn.execute('SELECT COUNT(*) FROM query_audit_logs').fetchone()[0] == 4
    assert conn.execute('SELECT COUNT(*) FROM sync_run_logs').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM schema_change_logs').fetchone()[0] == 1
    # 解析后的 created_at 为 datetime 可读格式（字符串 ISO 形式）
    ts = [r[0] for r in conn.execute(
        'SELECT created_at FROM query_audit_logs ORDER BY id').fetchall()]
    conn.close()
    assert ts[0].startswith('2026-08-20 10:30:00'), ts
    assert ts[1].startswith('2026-08-21 09:00:00'), ts
    assert ts[2].startswith('2026-08-22'), ts
    assert ts[3].startswith('2026-08-23 08:00:00'), ts

    # 主库旧表已删
    conn = sqlite3.connect(main_db)
    remaining = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    remaining.discard('sqlite_sequence')
    assert remaining == set(), f'主库不应残留: {remaining}'


def test_migrate_logs_tables_moves_and_is_idempotent(tmp_path):
    """存量归档：数据搬迁 + 幂等 + 主库无残留"""
    main_db = tmp_path / 'queryforge.db'
    logs_db = tmp_path / 'logs.db'

    # 构造"改造前"的旧主库：日志三表 + 一条配置表 + 若干行数据
    conn = sqlite3.connect(main_db)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE query_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            username TEXT, query TEXT NOT NULL, created_at TEXT);
        CREATE TABLE sync_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
            status TEXT, started_at TEXT);
        CREATE TABLE schema_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_log_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL, datasource_id INTEGER NOT NULL,
            change_type TEXT, created_at TEXT);
        INSERT INTO users (id, username) VALUES (1, 'admin');
        INSERT INTO query_audit_logs (user_id, username, query)
            VALUES (1, 'admin', 'Q1'), (1, 'admin', 'Q2');
        INSERT INTO sync_run_logs (job_id, status) VALUES (1, 'success');
        INSERT INTO schema_change_logs (run_log_id, job_id, datasource_id, change_type)
            VALUES (1, 1, 1, 'add');
    """)
    conn.commit()
    conn.close()

    # 日志库先由 create_all 建好带约束的空表（init_database 的顺序）
    _all_models()
    from sqlalchemy import create_engine

    from models.base import LogsBase
    LogsBase.metadata.create_all(create_engine(f'sqlite:///{logs_db}'))

    # 第一次迁移：数据进日志库，主库表被删
    _migrate_logs_tables(str(main_db), str(logs_db))
    conn = sqlite3.connect(logs_db)
    assert conn.execute('SELECT COUNT(*) FROM query_audit_logs').fetchone()[0] == 2
    assert conn.execute('SELECT COUNT(*) FROM sync_run_logs').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM schema_change_logs').fetchone()[0] == 1
    conn.close()
    conn = sqlite3.connect(main_db)
    remaining = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    # sqlite_sequence 为 SQLite 内部 AUTOINCREMENT 序列表，非业务表
    remaining.discard('sqlite_sequence')
    assert remaining == {'users'}, f'主库不应残留日志表: {remaining}'

    # 第二次迁移：幂等跳过，不报错不清数据
    _migrate_logs_tables(str(main_db), str(logs_db))
    conn = sqlite3.connect(logs_db)
    assert conn.execute('SELECT COUNT(*) FROM query_audit_logs').fetchone()[0] == 2
    conn.close()

    # 迁移后表带完整约束（PK/自增），与 create_all 结构一致
    ddl = sqlite3.connect(logs_db).execute(
        "SELECT sql FROM sqlite_master WHERE name='query_audit_logs'"
    ).fetchone()[0]
    assert 'PRIMARY KEY' in ddl.upper()
