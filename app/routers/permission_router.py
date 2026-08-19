"""RBAC 管理路由：角色、用户角色关系和角色资源权限。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AdminUser
from app.logger import log_audit
from models import SessionLocal
from models.role import Role, UserRole, RolePermission
from models.schema import DbSchema
from models.schema import DbTable, DbColumn
from models.user import User
from models.knowledge import KnowledgeItem
from models.sync import DataSource, SyncJobConfig

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
def permission_catalog(user: AdminUser):
    """返回权限页面所需的固定功能目录和数据资源目录。"""
    db = SessionLocal()
    try:
        schemas = db.query(DbSchema).order_by(DbSchema.name).all()
        return {
            'pages': [
                {'key': '/static/template/system/system_settings.html', 'name': '系统设置'},
                {'key': '/static/template/system/user_manage.html', 'name': '用户管理'},
                {'key': '/static/template/system/role_manage.html', 'name': '角色与权限'},
                {'key': '/static/template/system/scheduler_manage.html', 'name': '定时任务'},
                {'key': '/static/template/system/driver_manage.html', 'name': '驱动管理'},
                {'key': '/static/template/system/sync_manage.html', 'name': '同步管理'},
                {'key': '/static/template/system/security_manage.html', 'name': '安全中心'},
                {'key': '/static/template/schema/schema_view.html', 'name': '数据浏览'},
                {'key': '/static/template/knowledge.html', 'name': '知识库'},
                {'key': '/static/template/llm/llm_config.html', 'name': '模型配置'},
                {'key': '/static/template/llm/llm_logs.html', 'name': '调用日志'},
            ],
            'routes': [
                {'key': '/api/schema', 'name': 'Schema 管理'},
                {'key': '/api/sync', 'name': '元数据同步'},
                {'key': '/api/knowledge', 'name': '知识库'},
                {'key': '/api/llm-config', 'name': '模型配置'},
                {'key': '/api/scheduler', 'name': '系统定时任务'},
                {'key': '/api/audit', 'name': '安全审计'},
            ],
            'datasources': [{'id': item.id, 'name': item.name} for item in db.query(
                DataSource).order_by(DataSource.name).all()],
            'schemas': [{'id': item.id, 'name': item.name} for item in schemas],
            'tables': [{'id': table.id, 'schema_id': table.schema_id,
                        'name': table.name} for table in db.query(DbTable).order_by(DbTable.name).all()],
            'columns': [{'id': column.id, 'table_id': column.table_id,
                         'name': column.name} for column in db.query(DbColumn).order_by(DbColumn.name).all()],
            'metrics': [{'id': column.id, 'table_id': column.table_id,
                         'name': column.name} for column in db.query(DbColumn).filter(
                             DbColumn.is_measure == True).order_by(DbColumn.name).all()],
            'knowledge': [{'id': item.id, 'name': item.title or f'知识#{item.id}'}
                          for item in db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1).all()],
        }
    finally:
        db.close()


@router.get('/roles')
def list_roles(user: AdminUser):
    db = SessionLocal()
    try:
        return [{
            'id': role.id, 'name': role.name, 'code': role.code,
            'description': role.description or '', 'is_system': role.is_system,
            'user_count': db.query(UserRole).filter(UserRole.role_id == role.id).count(),
            'permission_count': db.query(RolePermission).filter(
                RolePermission.role_id == role.id).count(),
        } for role in db.query(Role).order_by(Role.id.asc()).all()]
    finally:
        db.close()


@router.post('/roles')
def create_role(req: RoleCreateRequest, user: AdminUser):
    name, code = req.name.strip(), req.code.strip()
    if not name or not code:
        raise HTTPException(400, '角色名称和编码不能为空')
    db = SessionLocal()
    try:
        if db.query(Role).filter((Role.code == code) | (Role.name == name)).first():
            raise HTTPException(400, '角色名称或编码已存在')
        role = Role(name=name, code=code, description=req.description, is_system=0)
        db.add(role)
        db.commit()
        log_audit(user, 'create_role', f'role={code}')
        return {'id': role.id, 'message': '角色创建成功'}
    finally:
        db.close()


@router.delete('/roles/{role_id}')
def delete_role(role_id: int, user: AdminUser):
    db = SessionLocal()
    try:
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
    finally:
        db.close()


@router.get('/users')
def list_users(user: AdminUser):
    db = SessionLocal()
    try:
        return [{'id': item.id, 'username': item.username,
                 'role': item.role, 'is_active': item.is_active}
                for item in db.query(User).order_by(User.id.asc()).all()]
    finally:
        db.close()


@router.get('/users/{user_id}/roles')
def get_user_roles(user_id: int, user: AdminUser):
    db = SessionLocal()
    try:
        return [{'id': role.id, 'name': role.name, 'code': role.code}
                for role in db.query(Role).join(UserRole, UserRole.role_id == Role.id)
                .filter(UserRole.user_id == user_id).all()]
    finally:
        db.close()


@router.put('/users/{user_id}/roles')
def set_user_roles(user_id: int, req: UserRolesRequest, user: AdminUser):
    db = SessionLocal()
    try:
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
    finally:
        db.close()


@router.get('/roles/{role_id}/users')
def get_role_users(role_id: int, user: AdminUser):
    db = SessionLocal()
    try:
        return [{'id': item.id, 'username': item.username, 'is_active': item.is_active}
                for item in db.query(User).join(UserRole, UserRole.user_id == User.id)
                .filter(UserRole.role_id == role_id).all()]
    finally:
        db.close()


@router.put('/roles/{role_id}/users')
def set_role_users(role_id: int, req: RoleUsersRequest, user: AdminUser):
    db = SessionLocal()
    try:
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
    finally:
        db.close()


@router.get('/roles/{role_id}/permissions')
def get_role_permissions(role_id: int, user: AdminUser):
    db = SessionLocal()
    try:
        if not db.query(Role).filter(Role.id == role_id).first():
            raise HTTPException(404, '角色不存在')
        return [{
            'id': item.id, 'permission_code': item.permission_code,
            'resource_type': item.resource_type, 'resource_id': item.resource_id,
            'resource_key': item.resource_key, 'access_type': item.access_type,
            'filter_expression': item.filter_expression,
        } for item in db.query(RolePermission).filter(
            RolePermission.role_id == role_id).all()]
    finally:
        db.close()


@router.put('/roles/{role_id}/permissions')
def set_role_permissions(role_id: int, req: RolePermissionsRequest, user: AdminUser):
    allowed_types = {'datasource', 'schema', 'table', 'column', 'knowledge', 'metric'}
    allowed_access = {'ALLOW', 'SELECT', 'FILTER', 'NONE', 'DENY'}
    if any(item.resource_type not in allowed_types or item.access_type not in allowed_access
           for item in req.permissions):
        raise HTTPException(400, '资源类型或权限级别无效')
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(404, '角色不存在')
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        db.add_all(RolePermission(
            role_id=role_id,
            permission_code='access',
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            resource_key=item.resource_key,
            access_type=item.access_type,
        ) for item in req.permissions)
        db.commit()
        log_audit(user, 'assign_role_permissions', f'role={role.code} count={len(req.permissions)}')
        return {'message': '角色权限已更新', 'count': len(req.permissions)}
    finally:
        db.close()


@router.get('/resources/{resource_type}')
def list_resources(resource_type: str, user: AdminUser):
    db = SessionLocal()
    try:
        if resource_type == 'schema':
            return [{'id': item.id, 'name': item.name}
                    for item in db.query(DbSchema).order_by(DbSchema.name).all()]
        if resource_type == 'knowledge':
            return [{'id': item.id, 'name': item.title or f'知识#{item.id}'}
                    for item in db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1).all()]
        raise HTTPException(400, '未知资源类型')
    finally:
        db.close()


@router.get('/datasources')
def list_datasource_schemas(user: AdminUser):
    db = SessionLocal()
    try:
        items = []
        for source in db.query(DataSource).order_by(DataSource.name).all():
            schemas = [row.target_schema_name for row in db.query(
                SyncJobConfig.target_schema_name).filter(
                SyncJobConfig.datasource_id == source.id).all()]
            items.append({'id': source.id, 'name': source.name, 'db_type': source.db_type,
                          'database': source.database, 'schemas': schemas})
        return {'items': items}
    finally:
        db.close()
