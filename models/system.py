"""系统配置模型 — 键值对存储"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models import Base


class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = 'system_config'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    key = Column(String(100), unique=True, nullable=False, comment='配置键')
    value = Column(Text, comment='配置值')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
