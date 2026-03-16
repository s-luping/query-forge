# -*- coding: UTF-8 -*-
"""
LLM调用记录管理路由
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.logger import logger
from app.auth import get_current_user
from models import LLMSessionLocal
from models.llm_log import LLMLog


router = APIRouter()


class LLMLogItem(BaseModel):
    """LLM调用记录项模型"""
    id: int
    user_id: int
    question: str
    model: str
    conditions: Optional[str]
    result: Optional[str]
    duration_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    status: Optional[str]
    error_message: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class LLMLogListResponse(BaseModel):
    """LLM调用记录列表响应"""
    items: List[LLMLogItem]
    total: int


class LLMLogStats(BaseModel):
    """LLM调用统计"""
    total_calls: int
    total_tokens: int
    total_prompt_tokens: int
    total_completion_tokens: int
    avg_duration_ms: float
    success_rate: float


@router.get("/list", response_model=LLMLogListResponse)
async def get_llm_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    user = Depends(get_current_user)
):
    """获取LLM调用记录列表"""
    try:
        user_id = user['user_id']
        db = LLMSessionLocal()
        
        try:
            query = db.query(LLMLog).filter(LLMLog.user_id == user_id)
            
            if status:
                query = query.filter(LLMLog.status == status)
            
            total = query.count()
            items = query.order_by(LLMLog.created_at.desc()).offset(offset).limit(limit).all()
            
            return LLMLogListResponse(
                items=[LLMLogItem.model_validate(item) for item in items],
                total=total
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")


@router.get("/stats", response_model=LLMLogStats)
async def get_llm_stats(
    user = Depends(get_current_user)
):
    """获取LLM调用统计"""
    try:
        user_id = user['user_id']
        db = LLMSessionLocal()
        
        try:
            total_calls = db.query(LLMLog).filter(LLMLog.user_id == user_id).count()
            
            success_calls = db.query(LLMLog).filter(
                LLMLog.user_id == user_id,
                LLMLog.status == 'success'
            ).count()
            
            from sqlalchemy import func
            stats = db.query(
                func.sum(LLMLog.total_tokens).label('total_tokens'),
                func.sum(LLMLog.prompt_tokens).label('prompt_tokens'),
                func.sum(LLMLog.completion_tokens).label('completion_tokens'),
                func.avg(LLMLog.duration_ms).label('avg_duration')
            ).filter(LLMLog.user_id == user_id).first()
            
            return LLMLogStats(
                total_calls=total_calls,
                total_tokens=stats.total_tokens or 0,
                total_prompt_tokens=stats.prompt_tokens or 0,
                total_completion_tokens=stats.completion_tokens or 0,
                avg_duration_ms=round(stats.avg_duration or 0, 2),
                success_rate=round(success_calls / total_calls * 100, 2) if total_calls > 0 else 0
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取LLM统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.get("/{log_id}", response_model=LLMLogItem)
async def get_llm_log(
    log_id: int,
    user = Depends(get_current_user)
):
    """获取单条LLM调用记录"""
    try:
        user_id = user['user_id']
        db = LLMSessionLocal()
        
        try:
            log = db.query(LLMLog).filter(
                LLMLog.id == log_id,
                LLMLog.user_id == user_id
            ).first()
            
            if not log:
                raise HTTPException(status_code=404, detail="记录不存在")
            
            return LLMLogItem.model_validate(log)
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")


@router.delete("/{log_id}")
async def delete_llm_log(
    log_id: int,
    user = Depends(get_current_user)
):
    """删除单条LLM调用记录"""
    try:
        user_id = user['user_id']
        db = LLMSessionLocal()
        
        try:
            log = db.query(LLMLog).filter(
                LLMLog.id == log_id,
                LLMLog.user_id == user_id
            ).first()
            
            if not log:
                raise HTTPException(status_code=404, detail="记录不存在")
            
            db.delete(log)
            db.commit()
            
            return {"message": "删除成功"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
