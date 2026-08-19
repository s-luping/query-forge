# -*- coding: UTF-8 -*-
"""数据源模型 — 外部数据库连接配置（数据源管理）

DataSource 原定义于 models/sync.py，现独立成模型文件以对应数据源管理功能。
同步任务（SyncJobConfig 等）仍见 models/sync.py。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from models.base import MainBase
from app.timezone import now_beijing


class DataSource(MainBase):
    """外部数据源 — 连接配置（密码加密存储，只读账号）"""
    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    name = Column(String(100), unique=True, nullable=False, comment='数据源名称')
    db_type = Column(String(30), nullable=False, comment='数据库类型: mysql/postgresql/sqlite/...')
    host = Column(String(200), default='localhost', comment='主机地址')
    port = Column(Integer, default=3306, comment='端口')
    database = Column(String(200), default='', comment='数据库名/schema名')
    username = Column(String(100), default='', comment='连接用户名(应只读)')
    password_enc = Column(Text, default='', comment='加密的密码(enc::前缀)')
    extra_params = Column(Text, default='{}', comment='额外连接参数(JSON)')
    status = Column(String(20), default='active', comment='状态: active/inactive/error')
    last_error = Column(Text, default='', comment='最近一次连接错误')
    last_tested_at = Column(DateTime, comment='最后测试时间')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True, comment='创建者')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')
