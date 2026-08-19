from datetime import datetime, timedelta
from typing import Annotated, Dict, Any, Optional

import jwt
from fastapi import Depends, HTTPException, Request

from app.logger import logger
from app.config import FALLBACK_EXPIRE_MINUTES
from app.timezone import now_beijing_aware
from models import SessionLocal
from models.user import User
from models.role import Role, UserRole

ALGORITHM = 'HS256'

try:
    import bcrypt
except ImportError:  # bcrypt 未安装时仅禁止哈希写入，不影响存量校验
    bcrypt = None


def hash_password(plain: str) -> str:
    """密码哈希（bcrypt）"""
    if bcrypt is None:
        raise RuntimeError('bcrypt 未安装，禁止明文存储密码: pip install bcrypt')
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def is_hashed(stored: str) -> bool:
    """判断存储值是否已是 bcrypt 哈希"""
    return bool(stored) and stored.startswith('$2')


def verify_password(plain: str, stored: str) -> bool:
    """校验密码：支持 bcrypt 哈希；历史明文仅用于比对后立即升级"""
    if not stored:
        return False
    if is_hashed(stored):
        if bcrypt is None:
            return False
        try:
            return bcrypt.checkpw(plain.encode('utf-8'), stored.encode('utf-8'))
        except ValueError:
            return False
    # 历史明文：比对成功由调用方负责重哈希落库
    return plain == stored


def _get_secret_key() -> str:
    """读取签名密钥：环境变量 QUERYFORGE_SECRET_KEY 优先，其次系统配置表。
    两处都没有时直接抛错拒绝服务，绝不回落到硬编码值。"""
    from app.config import SECRET_KEY as ENV_SECRET_KEY
    if ENV_SECRET_KEY:
        return ENV_SECRET_KEY
    try:
        from models.system import SystemSetting
        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == 'SECRET_KEY').first()
            if row is not None and str(row.value):
                return row.value
        finally:
            db.close()
    except Exception as e:
        raise RuntimeError(f'读取 SECRET_KEY 失败: {e}')
    raise RuntimeError(
        'SECRET_KEY 未配置：请设置环境变量 QUERYFORGE_SECRET_KEY，'
        '或在系统设置表中写入 SECRET_KEY')


def _get_token_expire_minutes() -> int:
    """从系统配置表读取 ACCESS_TOKEN_EXPIRE_MINUTES"""
    try:
        from models.system import SystemSetting
        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter(
                SystemSetting.key == 'ACCESS_TOKEN_EXPIRE_MINUTES').first()
            if row is not None and str(row.value):
                return int(row.value)
        finally:
            db.close()
    except Exception:
        pass
    return FALLBACK_EXPIRE_MINUTES


def authenticate_user(username: str, password: str):
    """验证用户（bcrypt 哈希；历史明文命中后自动升级为哈希）"""
    logger.debug(f"尝试验证用户: {username}")
    db = SessionLocal()
    try:
        login_user = db.query(User).filter(User.username == username).first()
        if login_user is None:
            # 恒定时间路径：也做一次哈希运算，避免用户名枚举计时差异
            verify_password(password, '$2b$12$' + 'x' * 53)
            login_user = None
        elif verify_password(password, login_user.password or ''):
            if not is_hashed(login_user.password):
                login_user.password = hash_password(password)
                db.commit()
                logger.info(f"用户 {username} 密码已自动升级为 bcrypt 哈希")
        else:
            login_user = None
    finally:
        db.close()
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
        expire = now_beijing_aware() + timedelta(minutes=expires_delta)
    else:
        expire = now_beijing_aware() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
    logger.debug(f"为用户 {data.get('username')} 创建访问令牌")
    return encoded_jwt


def resolve_token_user(token: Optional[str]) -> Optional[dict]:
    """解析 token → 当前用户字典；token 缺失/无效/过期/用户禁用/密码已变更 → None。

    供 FastAPI 依赖与 HTTP 中间件（静态模板守卫）共用，保证校验逻辑单一来源。
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None

    user_id = payload.get('user_id')
    username = payload.get('username')
    if not user_id or not username:
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id,
            User.username == username,
            User.is_active == 1
        ).first()
        if not user:
            return None
        # pwd_ts 不匹配说明密码已修改，旧 token 全部失效
        if abs(float(payload.get('pwd_ts', 0)) - float(user.pwd_ts or 0)) > 1e-6:
            return None
        role_codes = [r[0] for r in db.query(Role.code).join(
            UserRole, UserRole.role_id == Role.id
        ).filter(UserRole.user_id == user.id).all()]
        if user.role == 'admin' and 'admin' not in role_codes:
            role_codes.append('admin')
        return {"user_id": user.id, "username": user.username,
                "role": user.role, "roles": role_codes}
    finally:
        db.close()


async def get_current_user(request: Request):
    """从请求中获取当前用户（Bearer 头优先，其次 HttpOnly cookie）"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
    else:
        token = request.cookies.get('token')

    if not token:
        logger.warning("请求缺少认证token")
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    user = resolve_token_user(token)
    if user is None:
        logger.warning(f"无效/失效的token")
        raise HTTPException(status_code=401, detail="无效的token或登录已失效，请重新登录")
    logger.debug(f"用户认证成功: {user['username']}")
    return user


async def get_current_admin(request: Request) -> dict:
    """管理接口权限依赖：管理员直通，其他用户按角色路由权限校验。

    用法：def xxx(..., user: AdminUser): 由框架自动注入并完成鉴权。
    """
    user = await get_current_user(request)
    if user.get('role') == 'admin' or 'admin' in user.get('roles', []):
        return user
    from app.permissions import has_permission
    path = request.url.path
    if has_permission(user, path, 'route', path) or has_permission(
            user, 'route.view', 'route', path):
        return user
    if user.get('role') != 'admin':
        logger.warning(f"越权访问: user_id={user.get('user_id')} username={user.get('username')} 尝试访问管理员接口")
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ═══════════════════════════════════════════════════════════════════
# 类型化依赖别名 — 企业主流写法（FastAPI Annotated 依赖注入）
#   def generate_sql(request: TextToSqlRequest, user: CurrentUser):
#   def create_user(req: UserCreateRequest, user: AdminUser):
# 相比 `user=Depends(get_current_user)`：IDE 类型提示、Swagger 可读、
# 角色校验下沉到依赖层，业务函数不再重复写 _admin_only。
# ═══════════════════════════════════════════════════════════════════
CurrentUser = Annotated[Dict[str, Any], Depends(get_current_user)]
AdminUser = Annotated[Dict[str, Any], Depends(get_current_admin)]
