"""用户模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from models import Base


class User(Base):
    """用户表"""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    username = Column(String(50), unique=True, nullable=False, comment='用户名')
    password = Column(String(255), nullable=False, comment='密码')
    email = Column(String(100), comment='邮箱')
    role = Column(String(20), default='user', comment='角色(admin/user)')
    description = Column(String(255), comment='描述')
    is_active = Column(Integer, default=1, comment='启用状态')
    register_date = Column(DateTime, default=datetime.now, comment='注册时间')
    last_login = Column(DateTime, comment='最后登录')
