# -*- coding: UTF-8 -*-
"""
知识库路由 — 领域知识管理（业务口径/表关系/计算规则等，生成 SQL 时注入提示词）

数据层：models/knowledge.py 的 KnowledgeItem（表名 knowledge_items，字段 content）
API 契约：字段名为 content（与表字段一致），前端通过 /api/knowledge 访问。
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.auth import CurrentUser
from app.logger import logger, log_audit
from app.permissions import get_visible_knowledge_ids, is_admin
from models import SessionLocal
from models.knowledge import KnowledgeItem
from models.user import User

router = APIRouter()


class KnowledgeRequest(BaseModel):
    """知识库条目请求"""
    title: Optional[str] = None
    content: Optional[str] = None

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError('标题长度不能超过200个字符')
        return v

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if v is not None and len(v) > 5000:
            raise ValueError('知识内容长度不能超过5000个字符')
        return v


class KnowledgeResponse(BaseModel):
    """知识库条目响应"""
    id: int
    user_id: int
    title: Optional[str]
    content: Optional[str]
    is_active: int
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class KnowledgeListResponse(BaseModel):
    """知识库列表响应"""
    items: List[KnowledgeResponse]
    total: int


def _to_dict(item: KnowledgeItem) -> dict:
    return {
        'id': item.id,
        'user_id': item.user_id,
        'title': item.title,
        'content': item.content or '',
        'is_active': item.is_active,
        'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
        'updated_at': item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else None
    }


def get_all_knowledge(user: dict, limit: int = 20, offset: int = 0) -> tuple:
    """获取知识库条目（按用户权限过滤）"""
    db = SessionLocal()
    try:
        query = db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1)
        visible_ids = get_visible_knowledge_ids(user)
        if visible_ids is not None:
            if not visible_ids:
                return [], 0
            query = query.filter(KnowledgeItem.id.in_(visible_ids))
        total = query.count()
        items = query.order_by(KnowledgeItem.updated_at.desc()).limit(limit).offset(offset).all()
        return items, total
    finally:
        db.close()


def get_knowledge_safe(user_id: int, knowledge_id: int = None) -> dict:
    """安全获取知识条目（含用户授权校验，防越权读取）"""
    if not knowledge_id:
        return {}
    if not isinstance(knowledge_id, int) or knowledge_id <= 0:
        return {}
    db = SessionLocal()
    try:
        item = db.query(KnowledgeItem).filter(
            KnowledgeItem.id == knowledge_id,
            KnowledgeItem.is_active == 1
        ).first()
        if not item:
            return {}
        from models.role import Role, UserRole
        usr = db.query(User).filter(User.id == user_id).first()
        roles = [row[0] for row in db.query(Role.code).join(
            UserRole, UserRole.role_id == Role.id).filter(UserRole.user_id == user_id).all()]
        if not (usr and is_admin({'user_id': user_id, 'role': usr.role, 'roles': roles})):
            visible_ids = get_visible_knowledge_ids({
                'user_id': user_id, 'role': usr.role if usr else 'user', 'roles': roles})
            if visible_ids is not None and knowledge_id not in visible_ids:
                return {}
        return {
            'id': item.id,
            'title': item.title,
            'content': item.content or ''
        }
    finally:
        db.close()


@router.get("", response_model=KnowledgeListResponse)
def list_knowledge(
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """获取知识库列表"""
    items, total = get_all_knowledge(user, limit, offset)
    return {'items': [_to_dict(item) for item in items], 'total': total}


@router.post("", response_model=KnowledgeResponse)
def create_knowledge(
    data: KnowledgeRequest,
    user: CurrentUser
):
    """创建知识条目"""
    db = SessionLocal()
    try:
        item = KnowledgeItem(
            user_id=user['user_id'],
            title=data.title,
            content=data.content or ''
        )
        db.add(item)
        db.flush()
        db.commit()
        db.refresh(item)
        log_audit(user, "create_knowledge", f"title={data.title}")

        return _to_dict(item)
    except Exception as e:
        db.rollback()
        logger.error(f"创建知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
def get_knowledge(
    knowledge_id: int,
    user: CurrentUser
):
    """获取单条知识（权限过滤）"""
    db = SessionLocal()
    try:
        visible_ids = get_visible_knowledge_ids(user)
        if visible_ids is not None and knowledge_id not in visible_ids:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")

        item = db.query(KnowledgeItem).filter(
            KnowledgeItem.id == knowledge_id,
            KnowledgeItem.is_active == 1
        ).first()
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")

        return _to_dict(item)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/{knowledge_id}", response_model=KnowledgeResponse)
def update_knowledge(
    knowledge_id: int,
    data: KnowledgeRequest,
    user: CurrentUser
):
    """更新知识（所有者或管理员）"""
    db = SessionLocal()
    try:
        item = db.query(KnowledgeItem).filter(
            KnowledgeItem.id == knowledge_id
        ).first()
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能修改自己创建的知识")

        if data.title is not None:
            item.title = data.title
        if data.content is not None:
            item.content = data.content

        db.commit()
        db.refresh(item)
        log_audit(user, "update_knowledge", f"id={knowledge_id}")

        return _to_dict(item)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{knowledge_id}")
def delete_knowledge(
    knowledge_id: int,
    user: CurrentUser
):
    """删除知识（软删除，所有者或管理员）"""
    db = SessionLocal()
    try:
        item = db.query(KnowledgeItem).filter(
            KnowledgeItem.id == knowledge_id
        ).first()
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能删除自己创建的知识")

        item.is_active = 0
        db.commit()
        log_audit(user, "delete_knowledge", f"id={knowledge_id}")

        return {'message': '删除成功'}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
