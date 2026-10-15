# -*- coding: UTF-8 -*-
"""声明基类 — 主库 / 遥测库 / 日志库三库分离

主库（交互域，短事务，外键约束开启）: users / grants / llm_configs /
    db_schemas 三层 / data_sources / sync_job_configs / knowledge_items /
    conversations / conversation_messages / vector_index_meta /
    llm_usage_stats / system_settings
遥测库（LLM 调用追加型高频写）: llm_calls / llm_prompts
日志库（审计/同步历史追加型高频写，无跨库外键，应用层保证完整性）:
    query_audit_logs / sync_run_logs / schema_change_logs
"""
from sqlalchemy.orm import DeclarativeBase


class MainBase(DeclarativeBase):
    """主库（queryforge.db）表基类"""


class TelemetryBase(DeclarativeBase):
    """遥测库（llm_telemetry.db）表基类"""


class LogsBase(DeclarativeBase):
    """日志库（logs.db）表基类 — 审计/同步历史，跨库引用降级为普通索引列"""
