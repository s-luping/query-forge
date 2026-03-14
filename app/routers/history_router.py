# -*- coding: UTF-8 -*-
"""
历史记录路由 - SQL查询历史管理
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.security import HTTPBearer
from typing import List, Dict

from core.models import SqlHistoryItem, SqlHistoryResponse, RatingRequest
from app.logger import logger
from app.auth import get_current_user
from models import HistorySessionLocal
from models.sql_history import SqlHistory


router = APIRouter()

security = HTTPBearer(auto_error=False)


def add_history(query: str, sql_query: str, is_valid: bool, error_message: str, user_id: int, schema_name: str = None, knowledge_id: int = None) -> int:
    """添加历史记录"""
    db = HistorySessionLocal()
    try:
        history = SqlHistory(
            query=query,
            sql_query=sql_query,
            is_valid=is_valid,
            error_message=error_message,
            user_id=str(user_id),
            schema_name=schema_name,
            knowledge_id=knowledge_id
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history.id
    finally:
        db.close()


def get_history(user_id: int, limit: int = 20, offset: int = 0) -> tuple:
    """获取历史记录"""
    db = HistorySessionLocal()
    try:
        user_id_str = str(user_id)
        query = db.query(SqlHistory).filter(SqlHistory.user_id == user_id_str)
        
        total = query.count()
        items = query.order_by(SqlHistory.created_at.desc()).limit(limit).offset(offset).all()
        
        result = []
        for item in items:
            result.append({
                'id': item.id,
                'query': item.query,
                'sql_query': item.sql_query,
                'is_valid': bool(item.is_valid),
                'error_message': item.error_message,
                'user_id': item.user_id,
                'created_at': item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
                'rating': item.rating,
                'schema_name': item.schema_name,
                'knowledge_id': item.knowledge_id
            })
        
        return result, total
    finally:
        db.close()


def rate_history(history_id: int, user_id: int, rating: int) -> bool:
    """对历史记录进行评分"""
    db = HistorySessionLocal()
    try:
        user_id_str = str(user_id)
        history = db.query(SqlHistory).filter(
            SqlHistory.id == history_id,
            SqlHistory.user_id == user_id_str
        ).first()
        
        if not history:
            return False
        
        history.rating = rating
        db.commit()
        return True
    finally:
        db.close()


def get_successful_queries(user_id: int, limit: int = 5) -> List[Dict[str, str]]:
    """获取用户成功的查询历史（用于LLM参考，按评分降序）"""
    db = HistorySessionLocal()
    try:
        user_id_str = str(user_id)
        items = db.query(SqlHistory).filter(
            SqlHistory.user_id == user_id_str,
            SqlHistory.is_valid == True,
            SqlHistory.rating != None
        ).order_by(SqlHistory.rating.desc(), SqlHistory.created_at.desc()).limit(limit).all()
        
        result = []
        for item in items:
            result.append({
                'query': item.query,
                'sql': item.sql_query
            })
        return result
    finally:
        db.close()


@router.get("/history", response_model=SqlHistoryResponse)
async def get_sql_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user = Depends(get_current_user)
):
    """获取SQL历史记录"""
    try:
        user_id = user['user_id']
        items, total = get_history(user_id, limit, offset)

        history_items = [SqlHistoryItem(**item) for item in items]

        return SqlHistoryResponse(
            items=history_items,
            total=total
        )

    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@router.post("/history/rate")
async def rate_sql_history(
    request: RatingRequest,
    user = Depends(get_current_user)
):
    """对SQL历史记录进行评分"""
    try:
        if request.rating < 1 or request.rating > 5:
            raise HTTPException(status_code=400, detail="评分必须在1-5之间")

        user_id = user['user_id']
        success = rate_history(
            request.history_id,
            user_id,
            request.rating
        )

        if not success:
            raise HTTPException(status_code=404, detail="历史记录不存在或不属于该用户")

        return {"success": True, "message": "评分成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"评分失败: {e}")
        raise HTTPException(status_code=500, detail=f"评分失败: {str(e)}")


@router.delete("/history/{history_id}")
async def delete_sql_history(
    history_id: int,
    user = Depends(get_current_user)
):
    """删除SQL历史记录"""
    db = HistorySessionLocal()
    try:
        user_id_str = str(user['user_id'])
        history = db.query(SqlHistory).filter(
            SqlHistory.id == history_id,
            SqlHistory.user_id == user_id_str
        ).first()
        
        if not history:
            raise HTTPException(status_code=404, detail="历史记录不存在或不属于该用户")
        
        db.delete(history)
        db.commit()
        
        return {"success": True, "message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()
