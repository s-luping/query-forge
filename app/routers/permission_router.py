"""用户权限管理 — Schema/补充知识分配"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth import get_current_user
from app.logger import log_audit, log_error
from models import AppSessionLocal, SchemaSessionLocal, ExtraSessionLocal
from models.user import User, UserSchema, UserExtra
from models.schema import Schema
from models.extra_knowledge import ExtraKnowledge

router = APIRouter()


def _admin_only(user: dict):
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


# ── Models ───────────────────────────────────────────────────────

class UserItem(BaseModel):
    id: int; username: str; role: str; is_active: int
    class Config: from_attributes = True


class ResourceRecord(BaseModel):
    id: int; name: str; detail: str = None


class AssignRequest(BaseModel):
    user_id: int; resource_ids: List[str]


# ── 用户列表 ─────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserItem])
def list_users(user=Depends(get_current_user)):
    _admin_only(user)
    db = AppSessionLocal()
    try: return db.query(User).all()
    finally: db.close()


# ── 资源列表 ─────────────────────────────────────────────────────

@router.get("/resources/{resource_type}", response_model=List[ResourceRecord])
def list_resources(resource_type: str, user=Depends(get_current_user)):
    _admin_only(user)
    if resource_type == 'schema':
        db = SchemaSessionLocal()
        try:
            return [ResourceRecord(id=0, name=n[0]) for n in db.query(Schema.schema_name).distinct().all()]
        finally: db.close()
    if resource_type == 'extra':
        db = ExtraSessionLocal()
        try:
            items = db.query(ExtraKnowledge).filter(ExtraKnowledge.is_active == 1).all()
            return [ResourceRecord(id=e.id, name=e.title or f'知识#{e.id}') for e in items]
        finally: db.close()
    raise HTTPException(status_code=400, detail="未知资源类型")


# ── 用户已分配资源 ───────────────────────────────────────────────

@router.get("/users/{user_id}/resources/{resource_type}", response_model=List[str])
def get_user_resources(user_id: int, resource_type: str, user=Depends(get_current_user)):
    _admin_only(user)
    db = AppSessionLocal()
    try:
        if resource_type == 'schema':
            return [r.schema_name for r in db.query(UserSchema).filter(UserSchema.user_id == user_id).all() if r.schema_name]
        return [str(r.extra_id) for r in db.query(UserExtra).filter(UserExtra.user_id == user_id).all() if r.extra_id is not None]
    finally: db.close()


# ── 分配资源 ─────────────────────────────────────────────────────

@router.put("/users/{user_id}/resources/{resource_type}")
def assign_user_resources(user_id: int, resource_type: str, req: AssignRequest, user=Depends(get_current_user)):
    _admin_only(user)
    db = AppSessionLocal()
    try:
        if resource_type == 'schema':
            db.query(UserSchema).filter(UserSchema.user_id == user_id).delete()
            for name in req.resource_ids:
                db.add(UserSchema(user_id=user_id, schema_name=name or None))
        else:
            db.query(UserExtra).filter(UserExtra.user_id == user_id).delete()
            for rid in req.resource_ids:
                try: db.add(UserExtra(user_id=user_id, extra_id=int(rid) if rid else None))
                except ValueError: pass
        db.commit()
        log_audit(user, "assign_permission", f"user_id={user_id} resource={resource_type} ids={req.resource_ids}")
        return {"message": "资源分配已更新"}
    finally: db.close()
