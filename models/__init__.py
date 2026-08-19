# -*- coding: UTF-8 -*-
"""models 包 — ORM 模型定义（引擎/会话工厂见 db 包）

ORM 模型：
    base / user / role / schema / knowledge / conversation / llm /
    system / vector_index / security / sync / datasource

会话工厂（db 包提供，勿在此定义）：
    SessionLocal           → 主库 queryforge.db
    TelemetrySessionLocal  → 遥测库 llm_telemetry.db

兼容别名（逐步淘汰）：
    AppSessionLocal = SessionLocal
"""
from models.base import MainBase, TelemetryBase
from models.role import Role, UserRole, RolePermission

# 旧 Base（供未迁移脚本使用）
Base = MainBase
