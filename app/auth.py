# -*- coding: UTF-8 -*-
from datetime import datetime, timedelta
import jwt
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.logger import logger
from models import SessionLocal
from models.user import User
from fastapi import HTTPException, Depends, Request


def authenticate_user(username: str, password: str):
    """
    验证用户
    :param username: 用户名
    :param password: 密码
    :return: 用户对象，如果验证失败则返回None
    """
    logger.debug(f"尝试验证用户: {username}")
    with SessionLocal() as db:
        login_user = db.query(User).filter(User.username == username, User.password == password).first()
    if login_user:
        logger.info(f"用户验证成功: {username}")
    else:
        logger.warning(f"用户验证失败: {username}")
    return login_user


def create_access_token(data: dict, expires_delta=ACCESS_TOKEN_EXPIRE_MINUTES):
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta and expires_delta > 0 and expires_delta < 60 * 60 * 24 * 7:
        expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get('user_id')
        username = payload.get('username')
        
        if not user_id or not username:
            logger.warning(f"token缺少必要字段: user_id={user_id}, username={username}")
            raise HTTPException(status_code=401, detail="无效的token")
        
        db = SessionLocal()
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
