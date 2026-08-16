"""用户与权限模型 — 授权改为外键关联（替代旧的字符串 schema_name / 裸整数 extra_id）"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, UniqueConstraint
from models.base import MainBase


class User(MainBase):
    """用户表"""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    username = Column(String(50), unique=True, nullable=False, comment='用户名')
    password = Column(String(255), nullable=False, comment='密码(bcrypt哈希)')
    email = Column(String(100), comment='邮箱')
    role = Column(String(20), default='user', comment='角色(admin/user)')
    description = Column(String(255), comment='描述')
    is_active = Column(Integer, default=1, comment='启用状态')
    pwd_ts = Column(Float, default=0, comment='密码修改时间戳(用于撤销旧token)')
    register_date = Column(DateTime, default=datetime.now, comment='注册时间')
    last_login = Column(DateTime, comment='最后登录')


class UserSchemaGrant(MainBase):
    """用户可访问的 Schema（schema_id 为 NULL 表示全部可见）"""
    __tablename__ = 'user_schema_grants'
    __table_args__ = (UniqueConstraint('user_id', 'schema_id', name='uix_user_schema_grant'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    schema_id = Column(Integer, ForeignKey('db_schemas.id'), nullable=True, comment='Schema ID(NULL=全部)')


class UserKnowledgeGrant(MainBase):
    """用户可访问的知识库条目（knowledge_id 为 NULL 表示全部可见）"""
    __tablename__ = 'user_knowledge_grants'
    __table_args__ = (UniqueConstraint('user_id', 'knowledge_id', name='uix_user_knowledge_grant'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    knowledge_id = Column(Integer, ForeignKey('knowledge_items.id'), nullable=True, comment='知识ID(NULL=全部)')


class UserTableGrant(MainBase):
    """用户可访问的表（表级白名单，第三层权限）

    语义：同一 schema 内若配置了任意表授权 → 该用户仅可见名单内的表；
    未配置任何表授权的 schema → 该 schema 下全部表可见（默认行为）。
    """
    __tablename__ = 'user_table_grants'
    __table_args__ = (UniqueConstraint('user_id', 'table_id', name='uix_user_table_grant'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    table_id = Column(Integer, ForeignKey('db_tables.id'), nullable=False, index=True, comment='表ID')
