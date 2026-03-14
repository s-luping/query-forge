# -*- coding: UTF-8 -*-
"""
SQL查询历史模型
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from models import Base


class SqlHistory(Base):
    """SQL查询历史表"""
    __tablename__ = 'sql_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)
    sql_query = Column(Text, nullable=False)
    is_valid = Column(Boolean, default=True)
    error_message = Column(Text)
    user_id = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=func.now())
    rating = Column(Integer)
    schema_name = Column(String(100))
    knowledge_id = Column(Integer)
