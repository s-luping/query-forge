import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import (authenticate_user, create_access_token, hash_password,
                      _get_token_expire_minutes)
from app.config import COOKIE_SECURE
from app.limiter import limiter
from app.logger import logger
from app.timezone import now_beijing
from models import AppSessionLocal
from models.system import SystemSetting
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
                db_user.last_login = now_beijing()
                db.commit()
        finally:
            db.close()

        token_data = {"user_id": user.id, "username": user.username, "role": user.role,
                      "pwd_ts": float(user.pwd_ts or 0)}
        token = create_access_token(token_data)
        expire_minutes = _get_token_expire_minutes()
        response = JSONResponse(content={
            "user_id": user.id, "username": user.username, "role": user.role
        })
        # token 由服务端以 HttpOnly cookie 下发，禁止 JS 读取，防 XSS 窃取
        response.set_cookie(
            key="token", value=token, path="/",
            httponly=True, samesite="lax", secure=COOKIE_SECURE,
            max_age=60 * expire_minutes if 0 < expire_minutes < 60 * 24 * 7 else 900,
        )
        logger.info(f"登录成功 - user_id={user.id} username={username} role={user.role}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@limiter.limit("2/minute")
@router.post("/register")
def register(request: RegisterRequest):
    """注册（受 ALLOW_REGISTER 系统设置控制；企业内部可关闭，改由管理员创建账号）"""
    try:
        # 注册开关：管理员可在 系统设置 中关闭自助注册
        db_cfg = AppSessionLocal()
        try:
            allow = db_cfg.query(SystemSetting).filter(
                SystemSetting.key == 'ALLOW_REGISTER').first()
        finally:
            db_cfg.close()
        if allow is None or str(allow.value).lower() not in ('1', 'true', 'yes'):
            logger.warning(f"注册被管理员关闭: username={request.username}")
            raise HTTPException(status_code=403, detail="系统已关闭自助注册，请联系管理员开通账号")

        username = request.username
        password = request.password
        email = request.email

        if len(username) < 3:
            raise HTTPException(status_code=400, detail="用户名至少需要3个字符")

        # 统一强密码策略（与改密接口一致）
        _validate_password_strength(password)

        import time as _time
        db = AppSessionLocal()
        try:
            existing_user = db.query(User).filter(User.username == username).first()
            if existing_user:
                logger.warning(f"注册失败 - 用户名已存在: {username}")
                raise HTTPException(status_code=400, detail="用户名已存在")

            new_user = User(
                username=username,
                password=hash_password(password),
                email=email,
                role='user',
                is_active=0,  # 注册后待管理员审批激活，不可直接登录
                pwd_ts=_time.time(),
            )
            db.add(new_user)
            db.commit()

            logger.info(f"注册成功(待激活) - username={username} email={email}")
            return {"message": "注册成功，账号需管理员激活后方可登录", "username": username}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
