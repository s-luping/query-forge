# -*- coding: UTF-8 -*-
"""
补充知识路由 - 领域知识管理
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.security import HTTPBearer
from pydantic import BaseModel, field_validator
from typing import Optional, List

from app.logger import logger
from app.auth import get_current_user
from models import ExtraSessionLocal
from models.extra_knowledge import ExtraKnowledge


router = APIRouter()

security = HTTPBearer(auto_error=False)


class ExtraKnowledgeRequest(BaseModel):
    """补充知识请求"""
    title: Optional[str] = None
    sample_values_section: Optional[str] = None
    table_relations_section: Optional[str] = None
    domain_knowledge_section: Optional[str] = None
    
    @field_validator('sample_values_section')
    @classmethod
    def validate_sample_values(cls, v):
        if v and len(v) > 100:
            raise ValueError('字段示例值不能超过100个字符')
        return v
    
    @field_validator('table_relations_section')
    @classmethod
    def validate_table_relations(cls, v):
        if v and len(v) > 100:
            raise ValueError('表间关系不能超过100个字符')
        return v
    
    @field_validator('domain_knowledge_section')
    @classmethod
    def validate_domain_knowledge(cls, v):
        if v and len(v) > 500:
            raise ValueError('领域知识不能超过500个字符')
        return v


class ExtraKnowledgeResponse(BaseModel):
    """补充知识响应"""
    id: int
    user_id: int
    title: Optional[str]
    sample_values_section: Optional[str]
    table_relations_section: Optional[str]
    domain_knowledge_section: Optional[str]
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
        
        result = []
        for item in items:
            result.append({
                'id': item.id,
                'user_id': item.user_id,
                'title': item.title,
                'sample_values_section': item.sample_values_section,
                'table_relations_section': item.table_relations_section,
                'domain_knowledge_section': item.domain_knowledge_section,
                'is_active': item.is_active,
                'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
                'updated_at': item.updated_at.strftime('%Y-%m-%d %H:%M:%S') if item.updated_at else None
            })
        
        return result, total
    finally:
        db.close()


def get_extra_knowledge_by_id(user_id: int, knowledge_id: int) -> Optional[dict]:
    """获取单条补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user_id,
            ExtraKnowledge.is_active == 1
        ).first()
        
        if extra:
            return {
                'id': extra.id,
                'user_id': extra.user_id,
                'title': extra.title,
                'sample_values_section': extra.sample_values_section or '',
                'table_relations_section': extra.table_relations_section or '',
                'domain_knowledge_section': extra.domain_knowledge_section or '',
                'is_active': extra.is_active,
                'created_at': extra.created_at.strftime('%Y-%m-%d %H:%M:%S') if extra.created_at else None,
                'updated_at': extra.updated_at.strftime('%Y-%m-%d %H:%M:%S') if extra.updated_at else None
            }
        return None
    finally:
        db.close()


def get_extra_knowledge_for_llm(user_id: int) -> dict:
    """获取用于LLM的补充知识（合并所有有效知识）"""
    db = ExtraSessionLocal()
    try:
        items = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.user_id == user_id,
            ExtraKnowledge.is_active == 1
        ).all()
        
        sample_values = []
        table_relations = []
        domain_knowledge = []
        
        for item in items:
            if item.sample_values_section:
                sample_values.append(item.sample_values_section)
            if item.table_relations_section:
                table_relations.append(item.table_relations_section)
            if item.domain_knowledge_section:
                domain_knowledge.append(item.domain_knowledge_section)
        
        return {
            'sample_values_section': '\n'.join(sample_values) if sample_values else None,
            'table_relations_section': '\n'.join(table_relations) if table_relations else None,
            'domain_knowledge_section': '\n'.join(domain_knowledge) if domain_knowledge else None
        }
    finally:
        db.close()


def create_extra_knowledge(user_id: int, data: ExtraKnowledgeRequest) -> int:
    """创建补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = ExtraKnowledge(
            user_id=user_id,
            title=data.title,
            sample_values=data.sample_values,
            table_relations=data.table_relations,
            domain_knowledge=data.domain_knowledge,
            is_active=1
        )
        db.add(extra)
        db.commit()
        db.refresh(extra)
        return extra.id
    finally:
        db.close()


def update_extra_knowledge(user_id: int, knowledge_id: int, data: ExtraKnowledgeRequest) -> bool:
    """更新补充知识"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user_id,
            ExtraKnowledge.is_active == 1
        ).first()
        
        if not extra:
            return False
        
        if data.title is not None:
            extra.title = data.title
        if data.sample_values_section is not None:
            extra.sample_values_section = data.sample_values_section
        if data.table_relations_section is not None:
            extra.table_relations_section = data.table_relations_section
        if data.domain_knowledge_section is not None:
            extra.domain_knowledge_section = data.domain_knowledge_section
        
        db.commit()
        return True
    finally:
        db.close()


def delete_extra_knowledge(user_id: int, knowledge_id: int) -> bool:
    """删除补充知识（软删除）"""
    db = ExtraSessionLocal()
    try:
        extra = db.query(ExtraKnowledge).filter(
            ExtraKnowledge.id == knowledge_id,
            ExtraKnowledge.user_id == user_id
        ).first()
        
        if not extra:
            return False
        
        extra.is_active = 0
        db.commit()
        return True
    finally:
        db.close()


@router.get("/", response_model=ExtraKnowledgeListResponse)
async def list_extra_knowledge(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user = Depends(get_current_user)
):
    """获取用户的补充知识列表"""
    try:
        user_id = user['user_id']
        items, total = get_all_extra_knowledge(user_id, limit, offset)
        
        knowledge_items = [ExtraKnowledgeResponse(**item) for item in items]
        
        return ExtraKnowledgeListResponse(
            items=knowledge_items,
            total=total
        )

    except Exception as e:
        logger.error(f"获取补充知识列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/{knowledge_id}", response_model=ExtraKnowledgeResponse)
async def get_single_extra_knowledge(
    knowledge_id: int,
    user = Depends(get_current_user)
):
    """获取单条补充知识"""
    try:
        user_id = user['user_id']
        extra = get_extra_knowledge_by_id(user_id, knowledge_id)
        
        if not extra:
            raise HTTPException(status_code=404, detail="知识记录不存在")
        
        return ExtraKnowledgeResponse(**extra)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/")
async def create_new_extra_knowledge(
    request: ExtraKnowledgeRequest,
    user = Depends(get_current_user)
):
    """创建新的补充知识"""
    try:
        user_id = user['user_id']
        knowledge_id = create_extra_knowledge(user_id, request)
        
        return {"success": True, "message": "创建成功", "id": knowledge_id}

    except Exception as e:
        logger.error(f"创建补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{knowledge_id}")
async def update_existing_extra_knowledge(
    knowledge_id: int,
    request: ExtraKnowledgeRequest,
    user = Depends(get_current_user)
):
    """更新补充知识"""
    try:
        user_id = user['user_id']
        success = update_extra_knowledge(user_id, knowledge_id, request)
        
        if not success:
            raise HTTPException(status_code=404, detail="知识记录不存在或不属于该用户")
        
        return {"success": True, "message": "更新成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/{knowledge_id}")
async def delete_existing_extra_knowledge(
    knowledge_id: int,
    user = Depends(get_current_user)
):
    """删除补充知识"""
    try:
        user_id = user['user_id']
        success = delete_extra_knowledge(user_id, knowledge_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="知识记录不存在或不属于该用户")
        
        return {"success": True, "message": "删除成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除补充知识失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
