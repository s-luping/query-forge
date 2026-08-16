# -*- coding: UTF-8 -*-
"""用户权限管理 — 数据源 / 库(Schema) / 表 / 知识库 四层分配

前端契约（permission_manage.html）：
- Schema 资源以"名称"为标识（checkbox value = schema name）
- 知识库资源以 ID 为标识（checkbox value = String(knowledge.id)）
- 表级授权按 schema_id 维度配置（table_ids 为整数列表）
- 字段级(SELECT/FILTER/NONE)与行级规则见 /api/audit（安全与审计页）
本路由保持上述契约不变（资源类型标识：schema / knowledge）。
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AdminUser
from app.logger import log_audit
from models import SessionLocal
from models.user import User, UserSchemaGrant, UserKnowledgeGrant, UserTableGrant
from models.schema import DbSchema, DbTable
from models.knowledge import KnowledgeItem
from models.sync import DataSource, SyncJobConfig

router = APIRouter()


# ── Models ───────────────────────────────────────────────────────

class UserItem(BaseModel):
    id: int
    username: str
    role: str
    is_active: int

    class Config:
        from_attributes = True


class ResourceRecord(BaseModel):
    id: int
    name: str
    detail: str = None


class AssignRequest(BaseModel):
    user_id: int
    resource_ids: List[str]


class TableGrantRequest(BaseModel):
    """表级授权请求：table_ids 为空 = 清除该 schema 的表级限制（全部表可见）"""
    table_ids: List[int]


# ── 用户列表 ─────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserItem])
def list_users(user: AdminUser):
    db = SessionLocal()
    try:
        return db.query(User).all()
    finally:
        db.close()


class UserStatusRequest(BaseModel):
    is_active: int  # 1=激活 0=禁用


@router.put("/users/{user_id}/status")
def set_user_status(user_id: int, req: UserStatusRequest, user: AdminUser):
    """启用/禁用（激活）用户 — 新注册账号需管理员激活后方可登录"""
    if req.is_active not in (0, 1):
        raise HTTPException(status_code=400, detail="is_active 只能为 0 或 1")
    if user_id == user['user_id']:
        raise HTTPException(status_code=400, detail="不能修改自己的启用状态")
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        target.is_active = req.is_active
        if req.is_active == 1 and not target.pwd_ts:
            import time as _time
            target.pwd_ts = _time.time()
        db.commit()
        log_audit(user, "set_user_status", f"target={target.username}, is_active={req.is_active}")
        return {"success": True, "user_id": user_id, "is_active": req.is_active}
    finally:
        db.close()


# ── 资源列表 ─────────────────────────────────────────────────────

@router.get("/resources/{resource_type}", response_model=List[ResourceRecord])
def list_resources(resource_type: str, user: AdminUser):
    db = SessionLocal()
    try:
        if resource_type == 'schema':
            rows = db.query(DbSchema).order_by(DbSchema.name.asc()).all()
            return [ResourceRecord(id=r.id, name=r.name) for r in rows]
        if resource_type == 'knowledge':
            items = db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1).all()
            return [ResourceRecord(id=e.id, name=e.title or f'知识#{e.id}') for e in items]
    finally:
        db.close()
    raise HTTPException(status_code=400, detail="未知资源类型")


# ── 用户已分配资源 ───────────────────────────────────────────────

@router.get("/users/{user_id}/resources/{resource_type}", response_model=List[str])
def get_user_resources(user_id: int, resource_type: str, user: AdminUser):
    db = SessionLocal()
    try:
        if resource_type == 'schema':
            # schema 以名称标识；schema_id 为 NULL 的"全量"授权不返回具体名称
            rows = db.query(UserSchemaGrant, DbSchema.name).outerjoin(
                DbSchema, UserSchemaGrant.schema_id == DbSchema.id
            ).filter(UserSchemaGrant.user_id == user_id).all()
            return [name for _grant, name in rows if name]
        return [str(r.knowledge_id) for r in db.query(UserKnowledgeGrant).filter(
            UserKnowledgeGrant.user_id == user_id).all() if r.knowledge_id is not None]
    finally:
        db.close()


# ── 分配资源 ─────────────────────────────────────────────────────

@router.put("/users/{user_id}/resources/{resource_type}")
def assign_user_resources(user_id: int, resource_type: str, req: AssignRequest,
                          user: AdminUser):
    db = SessionLocal()
    try:
        if resource_type == 'schema':
            db.query(UserSchemaGrant).filter(UserSchemaGrant.user_id == user_id).delete()
            for name in req.resource_ids:
                if not name:
                    # 空串表示"全部可见"（schema_id = NULL）
                    db.add(UserSchemaGrant(user_id=user_id, schema_id=None))
                    break
                schema = db.query(DbSchema).filter(DbSchema.name == name).first()
                if schema:
                    db.add(UserSchemaGrant(user_id=user_id, schema_id=schema.id))
        else:
            db.query(UserKnowledgeGrant).filter(UserKnowledgeGrant.user_id == user_id).delete()
            for rid in req.resource_ids:
                if not rid:
                    db.add(UserKnowledgeGrant(user_id=user_id, knowledge_id=None))
                    break
                try:
                    db.add(UserKnowledgeGrant(user_id=user_id, knowledge_id=int(rid)))
                except ValueError:
                    pass
        db.commit()
        log_audit(user, "assign_permission",
                  f"user_id={user_id} resource={resource_type} ids={req.resource_ids}")
        return {"message": "资源分配已更新"}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 表级授权（第三层：库 → 表）
# ═══════════════════════════════════════════════════════════════════

@router.get("/users/{user_id}/tables/{schema_id}")
def get_user_table_grants(user_id: int, schema_id: int, user: AdminUser):
    """获取某 schema 下用户可见的表（含授权标记）。

    返回: {tables: [{id, name, description, granted}], restricted: bool}
    restricted=false 表示该 schema 未配置表级白名单（默认全部可见）。
    """
    db = SessionLocal()
    try:
        tables = db.query(DbTable).filter(DbTable.schema_id == schema_id).order_by(DbTable.name.asc()).all()
        granted_ids = {g.table_id for g in db.query(UserTableGrant).filter(
            UserTableGrant.user_id == user_id).all()}
        restricted = len(granted_ids) > 0
        return {
            "restricted": restricted,
            "tables": [{
                "id": t.id, "name": t.name,
                "description": t.description or '',
                "granted": t.id in granted_ids,
            } for t in tables],
        }
    finally:
        db.close()


@router.put("/users/{user_id}/tables/{schema_id}")
def set_user_table_grants(user_id: int, schema_id: int, req: TableGrantRequest,
                          user: AdminUser):
    """设置某 schema 下用户的表级白名单；table_ids 为空 = 清除限制（全部表可见）。

    注意：表必须属于该 schema，否则忽略。
    """
    db = SessionLocal()
    try:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        schema = db.query(DbSchema).filter(DbSchema.id == schema_id).first()
        if not schema:
            raise HTTPException(status_code=404, detail="schema 不存在")

        valid_ids = {t[0] for t in db.query(DbTable.id).filter(
            DbTable.schema_id == schema_id,
            DbTable.id.in_(req.table_ids)).all()} if req.table_ids else set()

        # 仅重建该 schema 相关的授权（不影响其他 schema）
        existing = db.query(UserTableGrant).join(
            DbTable, UserTableGrant.table_id == DbTable.id
        ).filter(UserTableGrant.user_id == user_id,
                 DbTable.schema_id == schema_id).all()
        for g in existing:
            db.delete(g)
        for tid in valid_ids:
            db.add(UserTableGrant(user_id=user_id, table_id=tid))
        db.commit()
        log_audit(user, "assign_table_permission",
                  f"user_id={user_id} schema={schema.name} table_ids={sorted(valid_ids)}")
        return {"message": "表级授权已更新",
                "restricted": len(valid_ids) > 0,
                "table_ids": sorted(valid_ids)}
    except HTTPException:
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 数据源 → 库 映射（供"数据源级"授权视图：按数据源批量分配其同步的库）
# ═══════════════════════════════════════════════════════════════════

@router.get("/datasources")
def list_datasource_schemas(user: AdminUser):
    """列出数据源及其同步到的库（schema 名），供权限管理按数据源批量授权。"""
    db = SessionLocal()
    try:
        ds_rows = db.query(DataSource).order_by(DataSource.name.asc()).all()
        result = []
        for ds in ds_rows:
            schema_names = [j.target_schema_name for j in db.query(
                SyncJobConfig.target_schema_name).filter(
                SyncJobConfig.datasource_id == ds.id).all()]
            result.append({
                "id": ds.id,
                "name": ds.name,
                "db_type": ds.db_type,
                "database": ds.database,
                "schemas": schema_names,
            })
        return {"items": result}
    finally:
        db.close()
