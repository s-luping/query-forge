"""对话数据模型 — 多轮连续对话 SQL 生成"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from models import Base


class Conversation(Base):
    """对话会话"""
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    title = Column(String(200), nullable=True, comment='对话标题')
    schema_name = Column(String(100), nullable=True, comment='关联模式名')
    db_type = Column(String(20), default="sqlite", comment='数据库类型')
    llm_config_id = Column(Integer, nullable=True, comment='使用的模型配置ID')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class ConversationMessage(Base):
    """对话消息"""
    __tablename__ = "conversation_messages"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    conversation_id = Column(Integer, nullable=False, index=True, comment='所属对话')
    role = Column(String(20), nullable=False, comment='user|assistant')
    content = Column(Text, nullable=False, comment='消息文本')
    sql = Column(Text, nullable=True, comment='提取的SQL(仅assistant)')
    is_valid = Column(Boolean, default=True, comment='SQL是否有效')
    error_message = Column(Text, nullable=True, comment='错误信息')
    columns = Column(Text, nullable=True, comment='结果列名(JSON数组)')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
