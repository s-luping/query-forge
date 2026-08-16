"""Schema 三层模型 — db_schemas / db_tables / db_columns

替代旧的"一行一字段 + 7 列联合唯一"反范式表：
- 库名/表名/表注释只存一次，不再每个字段行重复
- 列表/统计直接查三层，无需 GROUP BY
- 表级操作（改表注释、删表）= 一行操作
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from models.base import MainBase


class DbSchema(MainBase):
    """数据库（schema）层"""
    __tablename__ = 'db_schemas'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    owner_user_id = Column(Integer, nullable=True, index=True, comment='导入者用户ID')
    datasource_id = Column(Integer, ForeignKey('data_sources.id'), nullable=True,
                           index=True, comment='关联数据源ID(同步导入时写入；手动导入为空)')
    name = Column(String(100), unique=True, nullable=False, comment='Schema 名称')
    db_type = Column(String(30), default='', comment='数据库类型(mysql/postgresql/...)')
    description = Column(Text, comment='描述')
    source = Column(String(30), default='ddl', comment='来源: ddl|json|spider|sync')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class DbTable(MainBase):
    """表层 — 表级信息（表名、表注释）只存一次"""
    __tablename__ = 'db_tables'
    __table_args__ = (UniqueConstraint('schema_id', 'name', name='uix_table_schema_name'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=False, index=True, comment='所属 Schema')
    name = Column(String(150), nullable=False, comment='表名')
    description = Column(Text, comment='表注释')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')


class DbColumn(MainBase):
    """字段层"""
    __tablename__ = 'db_columns'
    __table_args__ = (UniqueConstraint('table_id', 'name', name='uix_column_table_name'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    table_id = Column(Integer, ForeignKey('db_tables.id'), nullable=False, index=True, comment='所属表')
    ordinal = Column(Integer, default=0, comment='字段顺序')
    name = Column(String(150), nullable=False, comment='字段名')
    data_type = Column(String(100), comment='数据类型')
    description = Column(Text, comment='字段描述')
    is_nullable = Column(Boolean, default=True, comment='是否可空')
    default_value = Column(String(200), comment='默认值')
    column_key = Column(String(10), default='', comment='键类型(PRI=主键)')
    foreign_key = Column(String(200), default='', comment='外键引用(table.column)')
    sample_values = Column(Text, comment='示例值(逗号分隔)')
    sensitive_level = Column(String(20), default='public', comment='敏感等级: public/internal/sensitive/confidential')
    is_dimension = Column(Boolean, default=False, comment='是否维度字段(可分组)')
    is_measure = Column(Boolean, default=False, comment='是否度量字段(可聚合)')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
