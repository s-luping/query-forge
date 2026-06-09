import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import authenticate_user, create_access_token
from app.limiter import limiter
from app.logger import logger
from models import AppSessionLocal
from models.user import User

router = APIRouter()


def _validate_password_strength(password: str):
    """验证密码强度：>=8位，含大小写字母+数字+特殊字符"""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少需要8个字符")
    if not re.search(r'[a-z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含小写字母")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含大写字母")
    if not re.search(r'\d', password):
        raise HTTPException(status_code=400, detail="密码必须包含数字")
    if not re.search(r'[!@#$%^&*(),.?\":{}|<>_\-+=;\[\]\\/`~]', password):
        raise HTTPException(status_code=400, detail="密码必须包含特殊字符")


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


@limiter.limit("2/minute")
@router.post("/login")
def login(request: LoginRequest):
    """登录"""
    try:
        username = request.username
        password = request.password

        user = authenticate_user(username, password)
        if user is None:
            logger.warning(f"登录失败 - 用户名或密码错误: {username}")
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.is_active:
            logger.warning(f"登录失败 - 用户未激活: {username}")
            raise HTTPException(status_code=401, detail="用户未激活")

        db = AppSessionLocal()
        try:
            db_user = db.query(User).filter(User.id == user.id).first()
            if db_user:
                db_user.last_login = datetime.now()
                db.commit()
        finally:
            db.close()

        response = {"user_id": user.id, "username": user.username, "role": user.role}
        token = create_access_token(response)
        logger.info(f"登录成功 - user_id={user.id} username={username} role={user.role}")
        return {"access_token": token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@limiter.limit("2/minute")
@router.post("/register")
def register(request: RegisterRequest):
    """注册"""
    try:
        username = request.username
        password = request.password
        email = request.email

        if len(username) < 3:
            raise HTTPException(status_code=400, detail="用户名至少需要3个字符")

        if len(password) < 6:
            raise HTTPException(status_code=400, detail="密码至少需要6个字符")

        db = AppSessionLocal()
        try:
            existing_user = db.query(User).filter(User.username == username).first()
            if existing_user:
                logger.warning(f"注册失败 - 用户名已存在: {username}")
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

            logger.info(f"注册成功 - username={username} email={email}")
            return {"message": "注册成功", "username": username}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
