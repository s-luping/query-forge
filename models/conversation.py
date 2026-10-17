"""对话数据模型 — 多轮连续对话 SQL 生成

与 LLM 遥测的关联：
- conversation_messages.llm_call_id → llm_telemetry.llm_calls.id（跨库逻辑引用）
- conversations.context_prompt_id  → llm_telemetry.llm_prompts.id（跨库逻辑引用）
跨库无法建外键，由 services/llm/telemetry.py 统一维护一致性。
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.timezone import now_beijing
from models.base import MainBase


class Conversation(MainBase):
    """对话会话"""
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    title = Column(String(200), nullable=True, comment='对话标题')
    schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=True, index=True, comment='关联 Schema')
    db_type = Column(String(20), default="sqlite", comment='数据库类型')
    llm_config_id = Column(Integer, nullable=True, comment='使用的模型配置ID')
    knowledge_id = Column(Integer, ForeignKey('knowledge_items.id'), nullable=True, comment='关联的知识库条目ID(兼容旧版单条)')
    knowledge_ids = Column(Text, nullable=True, comment='关联的知识库条目ID列表(JSON数组)，支持多选')
    schema_tables = Column(Text, nullable=True, comment='首轮召回表集合(JSON数组)，供追问轮累积召回')
    context_prompt_id = Column(Integer, nullable=True, comment='首轮 schema 上下文 prompt ID(→llm_prompts，跨库逻辑引用)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


class ConversationMessage(MainBase):
    """对话消息"""
    __tablename__ = "conversation_messages"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    conversation_id = Column(Integer, ForeignKey('conversations.id'), nullable=False, index=True, comment='所属对话')
    role = Column(String(20), nullable=False, comment='user|assistant')
    content = Column(Text, nullable=False, comment='消息文本')
    sql = Column(Text, nullable=True, comment='提取的SQL(仅assistant)')
    is_valid = Column(Boolean, default=True, comment='SQL是否有效')
    error_message = Column(Text, nullable=True, comment='错误信息')
    columns = Column(Text, nullable=True, comment='结果列名(JSON数组)')
    result_data = Column(Text, nullable=True, comment='查询结果持久化(JSON: {columns,rows,row_count,error})')
    permission_note = Column(Text, nullable=True, comment='权限提示(网关改写：行级过滤注入/敏感字段聚合，用户可见)')
    llm_call_id = Column(Integer, nullable=True, index=True, comment='关联的LLM调用ID(→llm_calls，跨库逻辑引用)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
