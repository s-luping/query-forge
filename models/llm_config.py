# -*- coding: UTF-8 -*-
"""
LLM配置模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
from models import Base


class LLMConfig(Base):
    """LLM API配置表"""
    __tablename__ = 'llm_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    api_key = Column(Text, nullable=False)
    base_url = Column(String(500))
    max_tokens = Column(Integer, default=8000)
    temperature = Column(Float, default=0.7)
    timeout = Column(Integer, default=300)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
