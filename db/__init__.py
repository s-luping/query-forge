# -*- coding: UTF-8 -*-
"""db 包 — 数据库引擎、会话工厂与初始化（非 ORM 模型）

会话工厂：
    SessionLocal           → 主库 queryforge.db（用户/配置/Schema/知识/对话/统计/设置）
    TelemetrySessionLocal  → 遥测库 llm_telemetry.db（llm_calls / llm_prompts）

兼容别名：
    AppSessionLocal = SessionLocal
"""
from db.database import (
    engine_main,
    engine_telemetry,
    SessionLocal,
    TelemetrySessionLocal,
    get_setting,
    init_database,
)

# 兼容别名：老代码中的 AppSessionLocal 全部指向主库
AppSessionLocal = SessionLocal
