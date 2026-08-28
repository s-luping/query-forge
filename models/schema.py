"""Schema 三层模型 — db_schemas / db_tables / db_columns

替代旧的"一行一字段 + 7 列联合唯一"反范式表：
- 库名/表名/表注释只存一次，不再每个字段行重复
- 列表/统计直接查三层，无需 GROUP BY
- 表级操作（改表注释、删表）= 一行操作
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from models.base import MainBase
from app.timezone import now_beijing


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
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


class DbTable(MainBase):
    """表层 — 表级信息（表名、表注释）只存一次"""
    __tablename__ = 'db_tables'
    __table_args__ = (UniqueConstraint('schema_id', 'name', name='uix_table_schema_name'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=False, index=True, comment='所属 Schema')
    name = Column(String(150), nullable=False, comment='表名')
    description = Column(Text, comment='表注释')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')


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
    sensitive_level = Column(String(20), default='public', index=True, comment='敏感等级: public/internal/sensitive/confidential')
    is_dimension = Column(Boolean, default=False, comment='是否维度字段(可分组)')
    is_measure = Column(Boolean, default=False, comment='是否度量字段(可聚合)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')


class DbTableRelation(MainBase):
    """表关系维护 — 人工维护的表间 JOIN 关系（生成 SQL 时注入提示词）

    说明：
        - left/right 仅为书写方向，语义上是对称的连接关系
        - 查询链路按聚合命中的表匹配两侧表名，渲染为 JOIN 提示
    """
    __tablename__ = 'db_table_relations'
    __table_args__ = (
        UniqueConstraint('left_schema_id', 'left_table', 'left_column',
                         'right_schema_id', 'right_table', 'right_column',
                         name='uix_relation_both_sides'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    # 兼容历史字段：取左表所属 schema（迁移后废弃单列约束，仅用于回看/审计）
    schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=True,
                       index=True, comment='兼容字段：左表所属 Schema')
    # 同数据源可跨库：左右两侧各自所属 schema（数据库）；两者可不同
    left_schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=False,
                            index=True, comment='左表所属 Schema')
    right_schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=False,
                             index=True, comment='右表所属 Schema')
    left_table = Column(String(150), nullable=False, comment='左表名')
    left_column = Column(String(150), nullable=False, comment='左表连接字段')
    right_table = Column(String(150), nullable=False, comment='右表名')
    right_column = Column(String(150), nullable=False, comment='右表连接字段')
    join_type = Column(String(20), default='INNER JOIN',
                       comment='连接方式: INNER JOIN/LEFT JOIN/RIGHT JOIN')
    relation_type = Column(String(20), default='1:N', comment='基数: 1:1/1:N/N:1/N:N')
    description = Column(Text, default='', comment='关系说明')
    created_by = Column(Integer, nullable=True, comment='创建人用户ID')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing,
                        comment='更新时间（北京时间）')
