# -*- coding: UTF-8 -*-
"""
LLM调用记录模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime
from models import Base


class LLMLog(Base):
    """LLM调用记录表"""
    __tablename__ = 'llm_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    question = Column(Text, nullable=False)
    model = Column(String(100), nullable=False)
    conditions = Column(Text)
    result = Column(Text)
    duration_ms = Column(Float)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    status = Column(String(20), default='success')
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)
