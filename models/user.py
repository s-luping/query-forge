"""用户与权限模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
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


class UserSchema(Base):
    """用户可访问的 Schema"""
    __tablename__ = 'user_schemas'
    __table_args__ = (UniqueConstraint('user_id', 'schema_name', name='uix_user_schema'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='用户ID')
    schema_name = Column(String(100), comment='Schema名(NULL=全部)')


class UserExtra(Base):
    """用户可访问的补充知识"""
    __tablename__ = 'user_extras'
    __table_args__ = (UniqueConstraint('user_id', 'extra_id', name='uix_user_extra'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='用户ID')
    extra_id = Column(Integer, nullable=True, comment='补充知识ID(NULL=全部)')
