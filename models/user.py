"""用户基础模型。权限关系由 models.role 的 RBAC 模型统一管理。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from models.base import MainBase
from app.timezone import now_beijing


class User(MainBase):
    """用户表"""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    username = Column(String(50), unique=True, nullable=False, comment='用户名')
    password = Column(String(255), nullable=False, comment='密码(bcrypt哈希)')
    email = Column(String(100), comment='邮箱')
    role = Column(String(20), default='user', comment='兼容字段，实际权限来自角色')
    description = Column(String(255), comment='描述')
    is_active = Column(Integer, default=1, comment='启用状态')
    pwd_ts = Column(Float, default=0, comment='密码修改时间戳(用于撤销旧token)')
    register_date = Column(DateTime, default=now_beijing, comment='注册时间（北京时间）')
    last_login = Column(DateTime, comment='最后登录')
