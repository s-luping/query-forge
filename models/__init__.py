# -*- coding: UTF-8 -*-
"""models 包 — 双库模型与初始化

会话工厂：
    SessionLocal           → 主库 queryforge.db（用户/配置/Schema/知识/对话/统计/设置）
    TelemetrySessionLocal  → 遥测库 llm_telemetry.db（llm_calls / llm_prompts）

兼容别名（逐步淘汰）：
    AppSessionLocal = SessionLocal
"""
from models.base import MainBase, TelemetryBase
from models.database import (
    engine_main,
    engine_telemetry,
    SessionLocal,
    TelemetrySessionLocal,
    init_database,
)

# 兼容别名：老代码中的 AppSessionLocal 全部指向主库
AppSessionLocal = SessionLocal
# 旧 Base（供未迁移脚本使用）
Base = MainBase
