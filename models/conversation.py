# -*- coding: UTF-8 -*-
"""
对话数据模型 — 支持多轮连续对话 SQL 生成
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from models import Base


class Conversation(Base):
    """对话会话"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=True)
    schema_name = Column(String(100), nullable=True)
    db_type = Column(String(20), default="sqlite")
    llm_config_id = Column(Integer, nullable=True)    # 复用的模型配置
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ConversationMessage(Base):
    """对话消息"""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    role = Column(String(20), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False)            # 用户消息文本 或 助手回复原文
    sql = Column(Text, nullable=True)                 # 提取的 SQL（仅 assistant）
    is_valid = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    columns = Column(Text, nullable=True)             # JSON list of column names
    created_at = Column(DateTime, default=datetime.now)
