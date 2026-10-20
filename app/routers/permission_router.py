"""RBAC 管理路由：角色、用户角色关系和角色资源权限。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import AdminUser
from app.limiter import LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit
from app.response import ok
from crud.base import session_scope
from crud.role import role_crud, role_permission_crud
from models.knowledge import KnowledgeItem
from models.role import Role, RolePermission, UserRole
from models.schema import DbSchema
from models.user import User

router = APIRouter()


class RoleCreateRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


class UserRolesRequest(BaseModel):
    role_ids: List[int]


class RoleUsersRequest(BaseModel):
    user_ids: List[int]


class RolePermissionItem(BaseModel):
    permission_code: str = 'access'
    resource_type: str
    resource_id: Optional[int] = None
    resource_key: Optional[str] = None
    access_type: str = 'ALLOW'
    filter_expression: Optional[str] = None


class RolePermissionsRequest(BaseModel):
    permissions: List[RolePermissionItem]


@router.get('/permission-catalog')
@limiter.limit(LIMIT_READ)
def permission_catalog(request: Request, user: AdminUser):
    """返回权限页面所需的固定功能目录和数据资源目录。"""
    return role_crud.get_permission_catalog()
@router.get('/roles')
@limiter.limit(LIMIT_READ)
def list_roles(request: Request, user: AdminUser):
    return role_crud.list_with_user_count()
@router.post('/roles')
@limiter.limit(LIMIT_WRITE)
def create_role(request: Request, req: RoleCreateRequest, user: AdminUser):
    name, code = req.name.strip(), req.code.strip()
    if not name or not code:
        raise HTTPException(400, '角色名称和编码不能为空')
    with session_scope() as db:
        if db.query(Role).filter((Role.code == code) | (Role.name == name)).first():
            raise HTTPException(400, '角色名称或编码已存在')
        role = Role(name=name, code=code, description=req.description, is_system=0)
        db.add(role)
        db.commit()
        log_audit(user, 'create_role', f'role={code}')
        return {'id': role.id, 'message': '角色创建成功'}
@router.delete('/roles/{role_id}')
@limiter.limit(LIMIT_WRITE)
def delete_role(request: Request, role_id: int, user: AdminUser):
    with session_scope() as db:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(404, '角色不存在')
        if role.is_system:
            raise HTTPException(400, '系统角色不可删除')
        db.query(UserRole).filter(UserRole.role_id == role_id).delete()
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        db.delete(role)
        db.commit()
        log_audit(user, 'delete_role', f'role={role.code}')
        return {'message': '角色已删除'}
@router.get('/users')
@limiter.limit(LIMIT_READ)
def list_users(request: Request, user: AdminUser):
    with session_scope() as db:
        return [{'id': item.id, 'username': item.username,
                 'role': item.role, 'is_active': item.is_active}
                for item in db.query(User).order_by(User.id.asc()).all()]
@router.get('/users/{user_id}/roles')
@limiter.limit(LIMIT_READ)
def get_user_roles(request: Request, user_id: int, user: AdminUser):
    with session_scope() as db:
        return [{'id': role.id, 'name': role.name, 'code': role.code}
                for role in db.query(Role).join(UserRole, UserRole.role_id == Role.id)
                .filter(UserRole.user_id == user_id).all()]
@router.put('/users/{user_id}/roles')
@limiter.limit(LIMIT_WRITE)
def set_user_roles(request: Request, user_id: int, req: UserRolesRequest, user: AdminUser):
    with session_scope() as db:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(404, '用户不存在')
        roles = db.query(Role).filter(Role.id.in_(req.role_ids)).all() if req.role_ids else []
        if len(roles) != len(set(req.role_ids)):
            raise HTTPException(400, '包含不存在的角色')
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        db.add_all(UserRole(user_id=user_id, role_id=role.id) for role in roles)
        target.role = 'admin' if any(role.code == 'admin' for role in roles) else 'user'
        db.commit()
        log_audit(user, 'assign_roles', f'target={target.username} role_ids={req.role_ids}')
        return {'message': '用户角色已更新'}
@router.get('/roles/{role_id}/users')
@limiter.limit(LIMIT_READ)
def get_role_users(request: Request, role_id: int, user: AdminUser):
    with session_scope() as db:
        return [{'id': item.id, 'username': item.username, 'is_active': item.is_active}
                for item in db.query(User).join(UserRole, UserRole.user_id == User.id)
                .filter(UserRole.role_id == role_id).all()]
@router.put('/roles/{role_id}/users')
@limiter.limit(LIMIT_WRITE)
def set_role_users(request: Request, role_id: int, req: RoleUsersRequest, user: AdminUser):
    with session_scope() as db:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(404, '角色不存在')
        valid_ids = {item.id for item in db.query(User.id).filter(User.id.in_(req.user_ids)).all()}
        if valid_ids != set(req.user_ids):
            raise HTTPException(400, '包含不存在的用户')
        db.query(UserRole).filter(UserRole.role_id == role_id).delete()
        db.add_all(UserRole(user_id=item_id, role_id=role_id) for item_id in valid_ids)
        db.commit()
        log_audit(user, 'assign_role_users', f'role={role.code} user_ids={sorted(valid_ids)}')
        return {'message': '角色用户已更新'}
@router.get('/roles/{role_id}/permissions')
@limiter.limit(LIMIT_READ)
def get_role_permissions(request: Request, role_id: int, user: AdminUser):
    with session_scope() as db:
        if not db.query(Role).filter(Role.id == role_id).first():
            raise HTTPException(404, '角色不存在')
        return [{
            'id': item.id, 'permission_code': item.permission_code,
            'resource_type': item.resource_type, 'resource_id': item.resource_id,
            'resource_key': item.resource_key, 'access_type': item.access_type,
            'filter_expression': item.filter_expression,
        } for item in db.query(RolePermission).filter(
            RolePermission.role_id == role_id).all()]
@router.put('/roles/{role_id}/permissions')
@limiter.limit(LIMIT_WRITE)
def set_role_permissions(request: Request, role_id: int, req: RolePermissionsRequest, user: AdminUser):
    allowed_types = {'datasource', 'schema', 'table', 'column', 'knowledge', 'metric', 'row'}
    allowed_access = {'ALLOW', 'SELECT', 'FILTER', 'NONE', 'DENY'}
    if any(item.resource_type not in allowed_types or item.access_type not in allowed_access
           for item in req.permissions):
        raise HTTPException(400, '资源类型或权限级别无效')
    if any(item.resource_type == 'row' and (item.resource_id is None or not (item.filter_expression or '').strip())
           for item in req.permissions):
        raise HTTPException(400, '行级过滤规则必须指定表且过滤表达式不能为空')
    role = role_crud.get_by_id(role_id)
    if not role:
        raise HTTPException(404, '角色不存在')
    role_permission_crud.replace_role_permissions(role_id, [
        {'permission_code': 'access', 'resource_type': item.resource_type,
         'resource_id': item.resource_id, 'resource_key': item.resource_key,
         'access_type': item.access_type, 'filter_expression': item.filter_expression}
        for item in req.permissions
    ])
    log_audit(user, 'assign_role_permissions', f'role={role.code} count={len(req.permissions)}')
    return {'message': '角色权限已更新', 'count': len(req.permissions)}
@router.get('/resources/{resource_type}')
@limiter.limit(LIMIT_READ)
def list_resources(request: Request, resource_type: str, user: AdminUser):
    with session_scope() as db:
        if resource_type == 'schema':
            return [{'id': item.id, 'name': item.name}
                    for item in db.query(DbSchema).order_by(DbSchema.name).all()]
        if resource_type == 'knowledge':
            return [{'id': item.id, 'name': item.title or f'知识#{item.id}'}
                    for item in db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1).all()]
        raise HTTPException(400, '未知资源类型')
@router.get('/datasources')
@limiter.limit(LIMIT_READ)
def list_datasource_schemas(request: Request, user: AdminUser):
    return ok({'items': role_crud.list_datasource_schemas()})