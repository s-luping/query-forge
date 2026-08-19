"""角色与统一权限模型。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.timezone import now_beijing
from models.base import MainBase


class Role(MainBase):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), unique=True, nullable=False)
    code = Column(String(80), unique=True, nullable=False, index=True)
    description = Column(String(255))
    is_system = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=now_beijing)


class UserRole(MainBase):
    __tablename__ = 'user_roles'
    __table_args__ = (UniqueConstraint('user_id', 'role_id', name='uix_user_role'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False, index=True)


class RolePermission(MainBase):
    __tablename__ = 'role_permissions'
    __table_args__ = (UniqueConstraint(
        'role_id', 'permission_code', 'resource_type', 'resource_id',
        name='uix_role_permission_resource'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False, index=True)
    permission_code = Column(String(120), nullable=False, index=True)
    resource_type = Column(String(30), nullable=False, default='route')
    resource_id = Column(Integer, nullable=True, index=True)
    resource_key = Column(String(255), nullable=True, index=True)
    access_type = Column(String(10), nullable=False, default='ALLOW')
    filter_expression = Column(Text)
    created_at = Column(DateTime, default=now_beijing)
