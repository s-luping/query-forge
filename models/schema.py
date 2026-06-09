"""DDL解析结果模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, UniqueConstraint
from models import Base


class Schema(Base):
    """数据库模式表"""
    __tablename__ = 'schema'
    __table_args__ = (
        UniqueConstraint('user_id', 'schema_name', 'table_name', 'column_name', 'column_type', 'column_key', 'foreign_key', name='uix_schema_user_table_column'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='所属用户')
    schema_name = Column(String(100), nullable=False, comment='模式名/数据库名')
    table_name = Column(String(100), nullable=False, comment='表名')
    table_description = Column(Text, comment='表注释')
    column_name = Column(String(100), nullable=False, comment='字段名')
    column_type = Column(String(100), comment='字段类型')
    column_description = Column(Text, comment='字段注释')
    column_key = Column(String(50), comment='键类型(PRI/UNI/MUL)')
    foreign_key = Column(String(100), comment='外键引用')
    is_nullable = Column(Boolean, default=True, comment='允许为空')
    default_value = Column(String(255), comment='默认值')
    sample_values = Column(Text, comment='示例值(逗号分隔)')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
