"""LLM 数据模型 — 配置（主库）+ 调用遥测四层中的三层

Token/对话数据放置架构：
    明细层  llm_calls        （遥测库）一次 API 调用一行，只存指标与小文本
    去重层  llm_prompts      （遥测库）system_prompt 按 content_hash 去重
    关联层  conversation_messages.llm_call_id（主库，跨库逻辑引用）
    聚合层  llm_usage_stats  （主库）按 天×用户×模型 汇总，scheduler 定时刷新
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Boolean, Date, UniqueConstraint
from models.base import MainBase, TelemetryBase
from app.timezone import now_beijing


# ═══════════════════════════════════════════════════════════════════
# 主库表
# ═══════════════════════════════════════════════════════════════════

class LLMConfig(MainBase):
    """LLM API 配置表（主库）

    api_key 字段存储 Fernet 加密后的密文（见 app/security/crypto.py），
    读取时通过 decrypt_api_key() 解密。
    """
    __tablename__ = 'llm_configs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    provider = Column(String(50), nullable=False, comment='模型供应商')
    model = Column(String(100), nullable=False, comment='模型名称')
    api_key = Column(Text, nullable=False, comment='API密钥(Fernet密文)')
    base_url = Column(String(500), comment='API地址')
    max_tokens = Column(Integer, default=8000, comment='最大Token数')
    temperature = Column(Float, default=0.2, comment='生成随机性')
    timeout = Column(Integer, default=300, comment='请求超时(秒)')
    is_default = Column(Boolean, default=False, comment='是否默认')
    is_active = Column(Boolean, default=True, comment='是否启用')
    is_public = Column(Boolean, default=False, comment='是否公开(所有用户可见)')
    description = Column(Text, comment='备注')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


class LLMUsageStat(MainBase):
    """LLM 用量聚合表 — 按 天×用户×模型 汇总（scheduler 定时刷新）"""
    __tablename__ = 'llm_usage_stats'
    __table_args__ = (UniqueConstraint('stat_date', 'user_id', 'model', name='uix_usage_day_user_model'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    stat_date = Column(Date, nullable=False, index=True, comment='统计日期')
    user_id = Column(Integer, nullable=False, index=True, comment='用户ID')
    provider = Column(String(50), default='', comment='模型供应商')
    model = Column(String(100), nullable=False, comment='模型名称')
    call_count = Column(Integer, default=0, comment='调用次数')
    success_count = Column(Integer, default=0, comment='成功次数')
    prompt_tokens = Column(Integer, default=0, comment='输入Token合计')
    completion_tokens = Column(Integer, default=0, comment='输出Token合计')
    total_tokens = Column(Integer, default=0, comment='总Token合计')
    cost = Column(Float, default=0.0, comment='成本合计')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


# ═══════════════════════════════════════════════════════════════════
# 遥测库表（高频追加写，与主库物理隔离）
# ═══════════════════════════════════════════════════════════════════

class LLMPrompt(TelemetryBase):
    """去重层 — system prompt 大文本按 content_hash 去重存储

    相同 schema 上下文的 N 次调用共享一行，日志库体积预计缩小 80%+。
    """
    __tablename__ = 'llm_prompts'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    content_hash = Column(String(64), unique=True, nullable=False, index=True, comment='SHA-256 内容哈希')
    content = Column(Text, nullable=False, comment='完整 prompt 文本')
    length = Column(Integer, default=0, comment='文本长度')
    created_at = Column(DateTime, default=now_beijing, comment='首次出现时间（北京时间）')


class LLMCall(TelemetryBase):
    """明细层 — 一次 LLM API 调用一行（替代旧 llm_logs）

    大文本（system_prompt）移入 llm_prompts 去重存储，本表只保留：
    - 关联键：prompt_id / conversation_id / message_id / config_id
    - 小文本：question（用户问题）、result（生成的 SQL）、conditions（查询条件）
    - 指标：tokens 三项 / cost / duration_ms / status
    """
    __tablename__ = 'llm_calls'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    conversation_id = Column(Integer, nullable=True, index=True, comment='关联对话ID(主库逻辑引用)')
    message_id = Column(Integer, nullable=True, index=True, comment='关联消息ID(主库逻辑引用)')
    config_id = Column(Integer, nullable=True, comment='使用的 LLM 配置ID')
    provider = Column(String(50), default='', comment='模型供应商')
    model = Column(String(100), nullable=False, comment='模型名称')
    purpose = Column(String(20), default='chat_sql', index=True, comment='调用目的: chat_sql|single|test')
    question = Column(Text, comment='用户问题')
    conditions = Column(Text, comment='查询条件')
    prompt_id = Column(Integer, nullable=True, index=True, comment='关联 llm_prompts.id')
    result = Column(Text, comment='生成结果(SQL)')
    duration_ms = Column(Float, comment='耗时(毫秒)')
    prompt_tokens = Column(Integer, default=0, comment='输入Token')
    completion_tokens = Column(Integer, default=0, comment='输出Token')
    total_tokens = Column(Integer, default=0, comment='总Token')
    cost = Column(Float, default=0.0, comment='调用成本')
    status = Column(String(20), default='success', index=True, comment='状态(success/warning/error)')
    error_message = Column(Text, comment='错误信息')
    created_at = Column(DateTime, default=now_beijing, index=True, comment='创建时间（北京时间）')
