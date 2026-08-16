"""知识库模型 — 表名 knowledge_items，字段 content（业务口径/表关系/计算规则等，生成 SQL 时注入提示词）"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from models.base import MainBase


class KnowledgeItem(MainBase):
    """知识库条目表"""
    __tablename__ = 'knowledge_items'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='创建者用户ID')
    title = Column(String(200), comment='知识标题')
    content = Column(Text, comment='知识内容')
    is_active = Column(Integer, default=1, comment='启用状态(1/0，0=软删除)')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
