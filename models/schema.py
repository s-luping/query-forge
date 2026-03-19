# -*- coding: UTF-8 -*-
"""

DDL解析结果模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.sql import func

from models import Base


class Schema(Base):
    """数据库模式表"""

    __tablename__ = 'schema'

    __table_args__ = (
        UniqueConstraint('user_id', 'schema_name', 'table_name', 'column_name', 'column_type', 'column_key', 'foreign_key', name='uix_schema_user_table_column'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    schema_name = Column(String(100), nullable=False)

    table_name = Column(String(100), nullable=False)

    table_description = Column(Text)

    column_name = Column(String(100), nullable=False)

    column_type = Column(String(100))

    column_description = Column(Text)

    column_key = Column(String(50))

    foreign_key = Column(String(100))

    is_nullable = Column(Boolean, default=True)

    default_value = Column(String(255))

    sample_values = Column(Text)

    created_at = Column(DateTime, default=func.now())
