# -*- coding: UTF-8 -*-
"""
用户模型
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from models import Base


class User(Base):
    """用户表"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    email = Column(String(100))
    role = Column(String(20), default='user')
    description = Column(String(255))
    is_active = Column(Integer, default=1)
    register_date = Column(DateTime, default=func.now())
    last_login = Column(DateTime)
