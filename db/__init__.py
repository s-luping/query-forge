# -*- coding: UTF-8 -*-
"""db 包 — 数据库引擎、会话工厂与初始化（非 ORM 模型）

模块结构：
  db/engine.py        引擎与会话工厂（方言自适应，SQLite/MySQL/PostgreSQL）
  db/sqlite_hooks.py  SQLite 专用 PRAGMA 与轻量迁移
  db/seed.py          种子数据（系统配置/管理员/角色）
  db/database.py      get_setting + init_database 编排

会话工厂（三库分离）：
    SessionLocal           → 主库（用户/配置/Schema/知识/对话/统计/设置）
    TelemetrySessionLocal  → 遥测库（llm_calls / llm_prompts）
    LogsSessionLocal       → 日志库（query_audit_logs / sync_run_logs / schema_change_logs）

兼容别名：
    AppSessionLocal = SessionLocal
"""
from db.database import (
    LogsSessionLocal,
    SessionLocal,
    TelemetrySessionLocal,
    engine_logs,
    engine_main,
    engine_telemetry,
    get_setting,
    init_database,
    is_sqlite,
)

# 兼容别名：老代码中的 AppSessionLocal 全部指向主库
AppSessionLocal = SessionLocal
