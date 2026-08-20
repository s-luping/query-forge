# -*- coding: UTF-8 -*-
"""数据库初始化编排层 — 薄入口，按角色委托给子模块

架构：
  db/engine.py        引擎与会话工厂（方言自适应，支持 SQLite/MySQL/PostgreSQL）
  db/sqlite_hooks.py  SQLite 专用 PRAGMA 与轻量迁移（仅 SQLite 时调用）
  db/seed.py          种子数据（所有数据库通用）
  db/database.py      本文件 — get_setting + init_database 编排

切换数据库只需设置环境变量：
  DATABASE_URL=mysql+pymysql://user:pass@host:3306/queryforge?charset=utf8mb4
  DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/queryforge
"""
import app.config as config
from app.logger import logger

# 从 engine.py 引入引擎与会话工厂（统一导出点）
from db.engine import (
    engine_main,
    engine_telemetry,
    SessionLocal,
    TelemetrySessionLocal,
    is_sqlite,
)


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
         SQLite 模式：遥测库为独立引擎；外部数据库：与主库同引擎
      3. SQLite 专用：轻量增量迁移（_ensure_column_sqlite）
      4. 种子数据：系统配置 + 默认管理员 + 角色
    """
    from models.base import MainBase, TelemetryBase
    from models import (
        user, role, schema, knowledge, conversation,
        llm, system, vector_index, security, sync, datasource,
    )  # noqa: F401

    # 1. 创建表结构
    MainBase.metadata.create_all(engine_main)

    # 2. 遥测表：SQLite 独立引擎 / 外部数据库同引擎
    if engine_telemetry is not engine_main:
        TelemetryBase.metadata.create_all(engine_telemetry)
    else:
        TelemetryBase.metadata.create_all(engine_main)

    # 3. SQLite 专用轻量迁移（外部数据库通过 create_all 建全量表，无需迁移）
    if is_sqlite:
        from db.sqlite_hooks import _ensure_column_sqlite
        _ensure_column_sqlite(
            config.MAIN_DB_PATH, 'conversation_messages', 'result_data', 'TEXT'
        )

    logger.info("主库表创建/检查完成")
    logger.info("遥测库表创建/检查完成")

    # 4. 种子数据（所有数据库通用）
    from db.seed import _seed_system_settings, create_default_admin, _seed_roles
    _seed_system_settings()
    create_default_admin()
    _seed_roles()
