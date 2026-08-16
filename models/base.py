# -*- coding: UTF-8 -*-
"""声明基类 — 主库与遥测库分离

主库（交互域，短事务，外键约束开启）: users / grants / llm_configs /
    db_schemas 三层 / knowledge_items / conversations / vector_index_meta /
    llm_usage_stats / system_settings
遥测库（LLM 调用追加型高频写）: llm_calls / llm_prompts
"""
from sqlalchemy.orm import DeclarativeBase


class MainBase(DeclarativeBase):
    """主库（queryforge.db）表基类"""


class TelemetryBase(DeclarativeBase):
    """遥测库（llm_telemetry.db）表基类"""
