from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException, Request

from app.logger import logger, audit_logger
from models import AppSessionLocal
from models.user import User

ALGORITHM = 'HS256'
_FALLBACK_SECRET_KEY = '***REMOVED***'
_FALLBACK_EXPIRE_MINUTES = 4320  # 3 天


def _get_secret_key() -> str:
    """从系统配置表读取 SECRET_KEY，不存在则返回默认值"""
    try:
        from models.system import SystemConfig
        db = AppSessionLocal()
        try:
            row = db.query(SystemConfig).filter(SystemConfig.key == 'SECRET_KEY').first()
            if row and row.value:
                return row.value
        finally:
            db.close()
    except Exception:
        pass
    return _FALLBACK_SECRET_KEY


def _get_token_expire_minutes() -> int:
    """从系统配置表读取 ACCESS_TOKEN_EXPIRE_MINUTES"""
    try:
        from models.system import SystemConfig
        db = AppSessionLocal()
        try:
            row = db.query(SystemConfig).filter(SystemConfig.key == 'ACCESS_TOKEN_EXPIRE_MINUTES').first()
            if row and row.value:
                return int(row.value)
        finally:
            db.close()
    except Exception:
        pass
    return _FALLBACK_EXPIRE_MINUTES


def authenticate_user(username: str, password: str):
    """验证用户"""
    logger.debug(f"尝试验证用户: {username}")
    with AppSessionLocal() as db:
        login_user = db.query(User).filter(User.username == username, User.password == password).first()
    if login_user:
        logger.info(f"用户验证成功: {username}")
    else:
        logger.warning(f"用户验证失败: {username}")
    return login_user


def create_access_token(data: dict, expires_delta=None):
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta is None:
        expires_delta = _get_token_expire_minutes()
    if 0 < expires_delta < 60 * 60 * 24 * 7:
        expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
    logger.debug(f"为用户 {data.get('username')} 创建访问令牌")
    return encoded_jwt


async def get_current_user(request: Request):
    """从请求中获取当前用户"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
    else:
        token = request.cookies.get('token')

    if not token:
        logger.warning("请求缺少认证token")
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get('user_id')
        username = payload.get('username')

        if not user_id or not username:
            logger.warning(f"token缺少必要字段: user_id={user_id}, username={username}")
            raise HTTPException(status_code=401, detail="无效的token")

        db = AppSessionLocal()
        try:
            user = db.query(User).filter(
                User.id == user_id,
                User.username == username,
                User.is_active == 1
            ).first()
            if not user:
                logger.warning(f"用户不存在或未激活: user_id={user_id}, username={username}")
                raise HTTPException(status_code=401, detail="用户不存在")
            logger.debug(f"用户认证成功: {username}")
            return {"user_id": user.id, "username": user.username, "role": user.role}
        finally:
            db.close()
    except jwt.ExpiredSignatureError:
        logger.warning("token已过期")
        raise HTTPException(status_code=401, detail="token已过期，请重新登录")
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效的token: {e}")
        raise HTTPException(status_code=401, detail="无效的token")
