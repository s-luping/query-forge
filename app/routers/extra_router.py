# -*- coding: UTF-8 -*-
"""
补充知识路由 - 领域知识管理
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.logger import logger
from models import ExtraSessionLocal
from models.extra_knowledge import ExtraKnowledge

router = APIRouter()

security = HTTPBearer(auto_error=False)


class ExtraKnowledgeRequest(BaseModel):
    """补充知识请求"""
    title: Optional[str] = None
    extra_knowledge: Optional[str] = None
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError('标题长度不能超过200个字符')
        return v
    
    @field_validator('extra_knowledge')
    @classmethod
    def validate_extra_knowledge(cls, v):
        if v is not None and len(v) > 5000:
            raise ValueError('补充知识长度不能超过5000个字符')
        return v


class ExtraKnowledgeResponse(BaseModel):
    """补充知识响应"""
    id: int
    user_id: int
    title: Optional[str]
    extra_knowledge: Optional[str]
    is_active: int
    created_at: Optional[str]
    updated_at: Optional[str]
    
    class Config:
        from_attributes = True


class ExtraKnowledgeListResponse(BaseModel):
    """补充知识列表响应"""
    items: List[ExtraKnowledgeResponse]
    total: int


def get_all_extra_knowledge(user_id: int, limit: int = 20, offset: int = 0) -> tuple:
    """获取用户所有补充知识"""
    db = ExtraSessionLocal()
    try:
        query = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.user_id == user_id,
            ExtraKnowledge.is_active == 1
        )
        
        total = query.count()
        items = query.order_by(ExtraKnowledge.updated_at.desc()).limit(limit).offset(offset).all()
        
        return items, total
    finally:
        db.close()


def get_extra_knowledge_safe(user_id: int, knowledge_id: int = None) -> dict:
    """安全获取补充知识"""
    if not knowledge_id:
        return {}
    
    if not isinstance(knowledge_id, int) or knowledge_id <= 0:
        return {}
    
    db = ExtraSessionLocal()
    try:
        item = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user_id,
            ExtraKnowledge.is_active == 1
        ).first()
        
        if not item:
            return {}
        
        return {
            'id': item.id,
            'title': item.title,
            'extra_knowledge': item.extra_knowledge or ''
        }
    finally:
        db.close()


@router.get("", response_model=ExtraKnowledgeListResponse)
def list_extra_knowledge(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user)
):
    """获取补充知识列表"""
    items, total = get_all_extra_knowledge(user['user_id'], limit, offset)
    
    return {
        'items': [{
            'id': item.id,
            'user_id': item.user_id,
            'title': item.title,
            'extra_knowledge': item.extra_knowledge or '',
            'is_active': item.is_active,
            'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
            'updated_at': item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else None
        } for item in items],
        'total': total
    }


@router.post("", response_model=ExtraKnowledgeResponse)
def create_extra_knowledge(
    data: ExtraKnowledgeRequest,
    user=Depends(get_current_user)
):
    """创建补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = ExtraKnowledge(
            user_id=user['user_id'],
            title=data.title,
            extra_knowledge=data.extra_knowledge or ''
        )
        db.add(extra)
        db.commit()
        db.refresh(extra)
        
        return {
            'id': extra.id,
            'user_id': extra.user_id,
            'title': extra.title,
            'extra_knowledge': extra.extra_knowledge or '',
            'is_active': extra.is_active,
            'created_at': extra.created_at.strftime('%Y-%m-%d %H:%M:%S') if extra.created_at else None,
            'updated_at': extra.updated_at.strftime('%Y-%m-%d %H:%M:%S') if extra.updated_at else None
        }
    except Exception as e:
        db.rollback()
        logger.error(f"创建补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{knowledge_id}", response_model=ExtraKnowledgeResponse)
def get_extra_knowledge(
    knowledge_id: int,
    user=Depends(get_current_user)
):
    """获取单条补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user['user_id'],
            ExtraKnowledge.is_active == 1
        ).first()
        
        if not extra:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")
        
        return {
            'id': extra.id,
            'user_id': extra.user_id,
            'title': extra.title,
            'extra_knowledge': extra.extra_knowledge or '',
            'is_active': extra.is_active,
            'created_at': extra.created_at.strftime('%Y-%m-%d %H:%M:%S') if extra.created_at else None,
            'updated_at': extra.updated_at.strftime('%Y-%m-%d %H:%M:%S') if extra.updated_at else None
        }
    finally:
        db.close()


@router.put("/{knowledge_id}", response_model=ExtraKnowledgeResponse)
def update_extra_knowledge(
    knowledge_id: int,
    data: ExtraKnowledgeRequest,
    user=Depends(get_current_user)
):
    """更新补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user['user_id']
        ).first()
        
        if not extra:
            raise HTTPException(status_code=404, detail="知识不存在")
        
        if data.title is not None:
            extra.title = data.title
        if data.extra_knowledge is not None:
            extra.extra_knowledge = data.extra_knowledge
        
        db.commit()
        db.refresh(extra)
        
        return {
            'id': extra.id,
            'user_id': extra.user_id,
            'title': extra.title,
            'extra_knowledge': extra.extra_knowledge or '',
            'is_active': extra.is_active,
            'created_at': extra.created_at.strftime('%Y-%m-%d %H:%M:%S') if extra.created_at else None,
            'updated_at': extra.updated_at.strftime('%Y-%m-%d %H:%M:%S') if extra.updated_at else None
        }
    except Exception as e:
        db.rollback()
        logger.error(f"更新补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{knowledge_id}")
def delete_extra_knowledge(
    knowledge_id: int,
    user=Depends(get_current_user)
):
    """删除补充知识（软删除）"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user['user_id']
        ).first()
        
        if not extra:
            raise HTTPException(status_code=404, detail="知识不存在")
        
        extra.is_active = 0
        db.commit()
        
        return {'message': '删除成功'}
    except Exception as e:
        db.rollback()
        logger.error(f"删除补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
