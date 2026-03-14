import time
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from app.auth import authenticate_user, create_access_token
from app.logger import logger
from pydantic import BaseModel
from typing import Optional
from models import SessionLocal
from models.user import User
from app.limiter import limiter



router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

@limiter.limit("2/minute")
@router.post("/login")
async def login(request: LoginRequest):
    """登录"""
    try:
        username = request.username
        password = request.password

        user = authenticate_user(username, password)
        if user is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.is_active:
            raise HTTPException(status_code=401, detail="用户未激活")
        
        db = SessionLocal()
        try:
            db_user = db.query(User).filter(User.id == user.id).first()
            if db_user:
                db_user.last_login = datetime.now()
                db.commit()
        finally:
            db.close()
        
        response = {"user_id": user.id, "username": user.username, "role": user.role}
        token = create_access_token(response)
        logger.info(f"用户登录成功: {username}")
        return {"access_token": token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")

@limiter.limit("2/minute")
@router.post("/register")
async def register(request: RegisterRequest):
    """注册"""
    try:
        username = request.username
        password = request.password
        email = request.email

        if len(username) < 3:
            raise HTTPException(status_code=400, detail="用户名至少需要3个字符")

        if len(password) < 6:
            raise HTTPException(status_code=400, detail="密码至少需要6个字符")

        db = SessionLocal()
        try:
            existing_user = db.query(User).filter(User.username == username).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="用户名已存在")

            new_user = User(
                username=username,
                password=password,
                email=email,
                role='user',
                is_active=1
            )
            db.add(new_user)
            db.commit()
            
            return {"message": "注册成功", "username": username}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")

