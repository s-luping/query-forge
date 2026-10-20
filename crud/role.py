# -*- coding: UTF-8 -*-
"""crud.role — 角色 / 用户角色 / 角色权限数据访问

用法：
    from crud.role import role_crud, user_role_crud, role_permission_crud
    roles = role_crud.list_all()
    perms = role_permission_crud.list(role_id=1)
"""
from typing import List, Optional

from sqlalchemy import func

from crud.base import BaseCrud, session_scope
from models.datasource import DataSource
from models.knowledge import KnowledgeItem
from models.role import Role, RolePermission, UserRole
from models.schema import DbColumn, DbSchema, DbTable
from models.sync import SyncJobConfig
from models.user import User


class RoleCrud(BaseCrud):
    model = Role

    def get_by_code(self, code: str) -> Optional[Role]:
        return self.get_one(code=code)

    def get_by_name(self, name: str) -> Optional[Role]:
        return self.get_one(name=name)

    def list_with_user_count(self) -> List[dict]:
        """角色列表 + 绑定用户数 + 权限数（聚合一次查询，避免 N+1）"""
        with session_scope() as db:
            roles = db.query(Role).order_by(Role.id.asc()).all()
            role_ids = [r.id for r in roles]
            user_counts = dict(db.query(UserRole.role_id, func.count(UserRole.id))
                               .filter(UserRole.role_id.in_(role_ids))
                               .group_by(UserRole.role_id).all()) if role_ids else {}
            perm_counts = dict(db.query(RolePermission.role_id, func.count(RolePermission.id))
                               .filter(RolePermission.role_id.in_(role_ids))
                               .group_by(RolePermission.role_id).all()) if role_ids else {}
            return [{
                'id': r.id, 'name': r.name, 'code': r.code,
                'description': r.description or '', 'is_system': r.is_system,
                'user_count': user_counts.get(r.id, 0),
                'permission_count': perm_counts.get(r.id, 0),
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            } for r in roles]

    def get_user_roles(self, user_id: int) -> List[Role]:
        """用户绑定的角色列表"""
        with session_scope() as db:
            rows = (db.query(Role)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .filter(UserRole.user_id == user_id)
                    .all())
            for r in rows:
                db.expunge(r)
            return rows

    def get_role_codes(self, user_id: int) -> List[str]:
        """用户角色 code 列表（admin 附加 'admin'）"""
        with session_scope() as db:
            codes = [r[0] for r in db.query(Role.code).join(
                UserRole, UserRole.role_id == Role.id
            ).filter(UserRole.user_id == user_id).all()]
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.role == 'admin' and 'admin' not in codes:
                codes.append('admin')
            return codes

    def set_user_roles(self, user_id: int, role_ids: List[int]) -> None:
        """覆盖式设置用户角色（删旧插新），并同步兼容字段 role"""
        with session_scope() as db:
            db.query(UserRole).filter(UserRole.user_id == user_id).delete()
            if role_ids:
                roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
                db.add_all(UserRole(user_id=user_id, role_id=r.id) for r in roles)
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.role = 'admin' if any(r.code == 'admin' for r in roles) else 'user'
        # 角色变更影响权限判定结果，立即失效缓存
        from app.permissions import invalidate_permission_cache
        invalidate_permission_cache()

    def get_permission_catalog(self) -> dict:
        """权限页面数据目录：固定页面/路由 + 六类资源（一次会话装载）"""
        with session_scope() as db:
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
                'datasources': [{'id': item.id, 'name': item.name}
                                for item in db.query(DataSource).order_by(DataSource.name).all()],
                'schemas': [{'id': item.id, 'name': item.name, 'datasource_id': item.datasource_id}
                            for item in schemas],
                'tables': [{'id': t.id, 'schema_id': t.schema_id, 'name': t.name}
                           for t in db.query(DbTable).order_by(DbTable.name).all()],
                'columns': [{'id': c.id, 'table_id': c.table_id, 'name': c.name}
                            for c in db.query(DbColumn).order_by(DbColumn.name).all()],
                'metrics': [{'id': c.id, 'table_id': c.table_id, 'name': c.name}
                            for c in db.query(DbColumn).filter(
                                DbColumn.is_measure == True).order_by(DbColumn.name).all()],
                'knowledge': [{'id': item.id, 'name': item.title or f'知识#{item.id}'}
                              for item in db.query(KnowledgeItem).filter(
                                  KnowledgeItem.is_active == 1).all()],
            }

    def list_datasource_schemas(self) -> List[dict]:
        """数据源 + 其同步出的目标库名（一次 IN 查询，避免 N+1）"""
        with session_scope() as db:
            sources = db.query(DataSource).order_by(DataSource.name).all()
            source_ids = [s.id for s in sources]
            schema_map = {}
            if source_ids:
                for ds_id, schema_name in db.query(
                        SyncJobConfig.datasource_id, SyncJobConfig.target_schema_name
                ).filter(SyncJobConfig.datasource_id.in_(source_ids)).all():
                    schema_map.setdefault(ds_id, []).append(schema_name)
            return [{'id': s.id, 'name': s.name, 'db_type': s.db_type,
                     'database': s.database, 'schemas': schema_map.get(s.id, [])}
                    for s in sources]


class UserRoleCrud(BaseCrud):
    model = UserRole


class RolePermissionCrud(BaseCrud):
    model = RolePermission

    def list_by_role(self, role_id: int) -> List[RolePermission]:
        return self.list(role_id=role_id)

    def replace_role_permissions(self, role_id: int, permissions: List[dict]) -> None:
        """覆盖式替换角色权限（删旧插新）"""
        with session_scope() as db:
            db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
            for p in permissions:
                db.add(RolePermission(
                    role_id=role_id,
                    permission_code=p.get('permission_code', 'access'),
                    resource_type=p.get('resource_type', 'route'),
                    resource_id=p.get('resource_id'),
                    resource_key=p.get('resource_key'),
                    access_type=p.get('access_type', 'ALLOW'),
                    filter_expression=p.get('filter_expression'),
                ))
        # 权限变更影响所有用户的可见性判定，立即失效缓存
        from app.permissions import invalidate_permission_cache
        invalidate_permission_cache()

    def list_role_grants(self, role_ids: List[int], resource_type: str = None):
        """查询角色在指定资源类型上的授权（用于权限判定）"""
        if not role_ids:
            return []
        with session_scope() as db:
            q = db.query(RolePermission).filter(RolePermission.role_id.in_(role_ids))
            if resource_type:
                q = q.filter(RolePermission.resource_type == resource_type)
            rows = q.all()
            # expunge 后再返回，避免会话外访问过期属性触发 DetachedInstanceError
            for r in rows:
                db.expunge(r)
            return rows


role_crud = RoleCrud()
user_role_crud = UserRoleCrud()
role_permission_crud = RolePermissionCrud()
