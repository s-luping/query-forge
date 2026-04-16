# -*- coding: UTF-8 -*-
"""
用户相关路由
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func

from app.auth import get_current_user
from app.logger import logger
from models import AppSessionLocal
from models.user import User

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """修改用户密码"""
    user_id = current_user['user_id']
    username = current_user['username']
    
    logger.info(f"用户 {username} 请求修改密码")
    
    db = AppSessionLocal()
    try:
        # 获取当前用户
        user = db.query(User).filter(
            User.id == user_id,
            User.username == username
        ).first()
        
        if not user:
            logger.warning(f"用户不存在: user_id={user_id}, username={username}")
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 验证当前密码
        if user.password != request.current_password:
            logger.warning(f"用户 {username} 当前密码验证失败")
            raise HTTPException(status_code=400, detail="当前密码不正确")
        
        # 更新密码
        user.password = request.new_password
        user.last_login = func.now()  # 更新最后登录时间作为修改标记
        db.commit()
        
        logger.info(f"用户 {username} 密码修改成功")
        return {"message": "密码修改成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"修改密码失败: {e}")
        raise HTTPException(status_code=500, detail="修改密码失败，请稍后重试")
    finally:
        db.close()


@router.get("/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """获取用户基本信息"""
    user_id = current_user['user_id']
    
    db = AppSessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
            
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "description": user.description,
            "register_date": user.register_date,
            "last_login": user.last_login
        }
    finally:
        db.close()