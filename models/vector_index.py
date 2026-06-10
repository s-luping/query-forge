"""向量索引元数据模型 — 持久化索引构建状态和位置"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models import Base


class VectorIndexMeta(Base):
    """向量索引元数据表"""
    __tablename__ = 'vector_index_meta'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    schema_name = Column(String(100), nullable=False, unique=True, index=True, comment='Schema 名称')
    status = Column(String(20), default='pending', comment='状态: pending|building|ready|stale|error')
    field_count = Column(Integer, default=0, comment='索引字段数')
    table_count = Column(Integer, default=0, comment='覆盖表数')
    dimension = Column(Integer, default=1024, comment='向量维度')
    file_path = Column(String(500), default='', comment='索引文件绝对路径')
    error_message = Column(Text, default='', comment='错误信息')
    built_at = Column(DateTime, default=None, comment='构建完成时间')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
