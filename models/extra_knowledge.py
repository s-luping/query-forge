# -*- coding: UTF-8 -*-
"""
补充知识模型
"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from models import Base


class ExtraKnowledge(Base):
    """外部知识表"""
    __tablename__ = 'extra_knowledge'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    title = Column(String(200))
    sample_values_section = Column(Text)
    table_relations_section = Column(Text)
    domain_knowledge_section = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
