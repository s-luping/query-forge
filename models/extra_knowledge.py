"""补充知识模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from models import Base


class ExtraKnowledge(Base):
    """外部知识表"""
    __tablename__ = 'extra_knowledge'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, comment='所属用户')
    title = Column(String(200), comment='知识标题')
    extra_knowledge = Column(Text, comment='知识内容')
    is_active = Column(Integer, default=1, comment='启用状态')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
