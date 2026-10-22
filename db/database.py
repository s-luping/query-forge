# -*- coding: UTF-8 -*-
"""数据库初始化编排层 — 薄入口，按角色委托给子模块

架构：
  db/engine.py        引擎与会话工厂（方言自适应，支持 SQLite/MySQL/PostgreSQL）
  db/sqlite_hooks.py  SQLite 专用 PRAGMA 与轻量迁移（仅 SQLite 时调用）
  db/seed.py          种子数据（所有数据库通用）
  db/database.py      本文件 — get_setting + init_database 编排

切换数据库只需修改 app/settings.py 中 DATABASE_URL 的值：
  DATABASE_URL = 'mysql+pymysql://user:pass@host:3306/queryforge?charset=utf8mb4'
  DATABASE_URL = 'postgresql+psycopg2://user:pass@host:5432/queryforge'
"""
import app.settings as config
from app.logger import logger

# 从 engine.py 引入引擎与会话工厂（统一导出点）
from db.engine import (
    LogsSessionLocal,
    SessionLocal,
    TelemetrySessionLocal,
    engine_logs,
    engine_main,
    engine_telemetry,
    is_sqlite,
)

# 统一导出点：db 包从此处转发，供上层统一 import
__all__ = ['SessionLocal', 'TelemetrySessionLocal', 'LogsSessionLocal',
           'engine_main', 'engine_telemetry', 'engine_logs',
           'is_sqlite', 'get_setting', 'init_database']


def get_setting(key: str, default: str = '') -> str:
    """读取系统配置：数据库 system_settings 优先（前台用户改过的值），
    其次回落 config 中同名变量的初始值；都没有则返回 default。"""
    from models.system import SystemSetting
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row is not None and str(row.value) not in ('', 'None'):
            return str(row.value)
    finally:
        db.close()
    return str(getattr(config, key, '') or default)


def init_database():
    """初始化表结构 + 种子数据 — 所有数据库类型通用

    流程：
      1. create_all 创建主库表（MainBase）
      2. create_all 创建遥测库表（TelemetryBase）
      3. create_all 创建日志库表（LogsBase）
         SQLite 模式：遥测/日志库为独立引擎；外部数据库：与主库同引擎
      4. SQLite 专用：轻量增量迁移（_ensure_column_sqlite）+ 日志表归档迁移
      5. 种子数据：系统配置 + 默认管理员 + 角色
    """
    from models.base import LogsBase, MainBase, TelemetryBase

    # 1. 创建表结构
    MainBase.metadata.create_all(engine_main)

    # 2. 遥测表：SQLite 独立引擎 / 外部数据库同引擎
    if engine_telemetry is not engine_main:
        TelemetryBase.metadata.create_all(engine_telemetry)
    else:
        TelemetryBase.metadata.create_all(engine_main)

    # 3. 日志表：SQLite 独立引擎 / 外部数据库同引擎
    if engine_logs is not engine_main:
        LogsBase.metadata.create_all(engine_logs)
    else:
        LogsBase.metadata.create_all(engine_main)

    # 4. SQLite 专用轻量迁移（外部数据库通过 create_all 建全量表，无需迁移）
    if is_sqlite:
        from db.sqlite_hooks import _ensure_column_sqlite
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'conversation_messages', 'result_data', 'TEXT'
        )
        # 知识库 typed 结构化字段（存量 SQLite 库增量迁移；新库由 create_all 建全量表）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'knowledge_type', 'VARCHAR(50)'
        )
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'aliases', 'TEXT'
        )
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'payload', 'TEXT'
        )
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'scope_schema_id', 'INTEGER'
        )
        # 表关系支持同数据源跨库：left/right 各自所属 schema（存量行用旧 schema_id 回填）
        from db.sqlite_hooks import _migrate_relation_cross_db
        _migrate_relation_cross_db(config.MAIN_DB_PATH)
        # 对话首轮召回表集合（供追问轮累积召回；存量库增量迁移）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'conversations', 'schema_tables', 'TEXT'
        )
        # 对话支持多知识库（knowledge_ids JSON 数组；存量库增量迁移）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'conversations', 'knowledge_ids', 'TEXT'
        )
        # 对话消息权限提示（网关行级过滤注入/敏感字段聚合，用户可见；存量库增量迁移）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'conversation_messages', 'permission_note', 'TEXT'
        )
        # 知识库全局发布与常驻上下文（存量条目统一置 personal，行为不变；管理员按需重新发布）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'visibility',
            "VARCHAR(20) DEFAULT 'personal'"
        )
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'knowledge_items', 'is_pinned', 'INTEGER DEFAULT 0'
        )
        # 存量遥测库补列：深度思考模型的输出 Token 明细
        _ensure_column_sqlite(
            config.TELEMETRY_DB_PATH, 'llm_calls', 'reasoning_tokens', 'INTEGER'
        )
        # LLM 配置思考模式开关（存量 SQLite 库增量迁移；新库由 create_all 建全量表）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'llm_configs', 'thinking_mode', "VARCHAR(20) DEFAULT 'auto'"
        )
        # LLM 配置状态（normal=正常 / arrears=欠费，余额不足自动标记；存量库增量迁移）
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'llm_configs', 'status', "VARCHAR(20) DEFAULT 'normal'"
        )
        # 高频过滤字段的普通索引（存量库补建；新库由 create_all 一并创建）
        from db.sqlite_hooks import (
            _ensure_indexes_sqlite,
            _ensure_logs_indexes,
            _ensure_telemetry_indexes,
        )
        _ensure_indexes_sqlite(config.MAIN_DB_PATH)
        _ensure_telemetry_indexes(config.TELEMETRY_DB_PATH)
        _ensure_logs_indexes(config.LOGS_DB_PATH)
        # 存量库归档：主库三张日志表迁入日志库（幂等，已迁过则跳过）
        from db.sqlite_hooks import _migrate_logs_tables
        _migrate_logs_tables(config.MAIN_DB_PATH, config.LOGS_DB_PATH)

    logger.info("主库表创建/检查完成")
    logger.info("遥测库表创建/检查完成")
    logger.info("日志库表创建/检查完成")

    # 4. 种子数据（所有数据库通用）
    from db.seed import _seed_roles, _seed_system_settings, create_default_admin
    _seed_system_settings()
    create_default_admin()
    _seed_roles()
