# -*- coding: UTF-8 -*-
"""
用户相关路由
- 普通用户：修改密码、个人资料
- 管理员：用户管理 CRUD（列表/创建/编辑/重置密码/删除）
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AdminUser, CurrentUser, hash_password, verify_password
from app.logger import logger, log_audit
from app.routers.base_router import _validate_password_strength
from models import SessionLocal
from models.user import User

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: CurrentUser,
):
    """修改用户密码"""
    user_id = current_user['user_id']
    username = current_user['username']

    logger.info(f"用户 {username} 请求修改密码")

    db = SessionLocal()
    try:
        # 获取当前用户
        user = db.query(User).filter(
            User.id == user_id,
            User.username == username
        ).first()

        if not user:
            logger.warning(f"用户不存在: user_id={user_id}, username={username}")
            raise HTTPException(status_code=404, detail="用户不存在")

        # 验证当前密码（bcrypt；历史明文自动升级）
        if not verify_password(request.current_password, user.password or ''):
            logger.warning(f"用户 {username} 当前密码验证失败")
            raise HTTPException(status_code=400, detail="当前密码不正确")

        # 统一强密码策略
        _validate_password_strength(request.new_password)

        # 更新密码（哈希）+ 刷新 pwd_ts 使所有旧 token 失效
        import time as _time
        user.password = hash_password(request.new_password)
        user.pwd_ts = _time.time()
        user.last_login = datetime.now()
        db.commit()

        logger.info(f"用户 {username} 密码修改成功")
        log_audit(current_user, "change_password")
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
async def get_user_profile(current_user: CurrentUser):
    """获取用户基本信息"""
    user_id = current_user['user_id']

    db = SessionLocal()
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


# ═══════════════════════════════════════════════════════════════════
# 管理员用户管理（AdminUser 依赖：未登录 401 / 非管理员 403）
# ═══════════════════════════════════════════════════════════════════

class UserCreateRequest(BaseModel):
    """管理员创建用户"""
    username: str
    password: str
    email: Optional[str] = None
    role: str = 'user'           # admin / user
    description: Optional[str] = None
    is_active: int = 1           # 1=启用 0=禁用


class UserUpdateRequest(BaseModel):
    """管理员编辑用户（字段均可选，只更新传入的字段）"""
    email: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


class ResetPasswordRequest(BaseModel):
    """管理员重置用户密码"""
    new_password: str


def _validate_role(role: str):
    if role not in ('admin', 'user'):
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")


def _count_admins(db) -> int:
    return db.query(User).filter(User.role == 'admin').count()


def _get_user_or_404(db, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/list")
def list_users(user: AdminUser):
    """管理员：用户列表（全字段，含启用状态/注册/最后登录）"""
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id.asc()).all()
        return [{
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "description": u.description,
            "is_active": u.is_active,
            "register_date": u.register_date,
            "last_login": u.last_login,
        } for u in users]
    finally:
        db.close()


@router.post("/create")
def create_user(req: UserCreateRequest, user: AdminUser):
    """管理员：创建用户（用户名唯一 + 强密码策略；可指定角色与启用状态）"""
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少需要3个字符")
    _validate_role(req.role)
    if req.is_active not in (0, 1):
        raise HTTPException(status_code=400, detail="is_active 只能为 0 或 1")
    _validate_password_strength(req.password)

    import time as _time
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == req.username).first():
            logger.warning(f"创建用户失败 - 用户名已存在: {req.username}")
            raise HTTPException(status_code=400, detail="用户名已存在")

        new_user = User(
            username=req.username,
            password=hash_password(req.password),
            email=req.email,
            role=req.role,
            description=req.description,
            is_active=req.is_active,
            pwd_ts=_time.time(),
        )
        db.add(new_user)
        db.commit()
        logger.info(f"管理员 {user['username']} 创建用户: {req.username} role={req.role}")
        log_audit(user, "create_user",
                  f"target={req.username} role={req.role} is_active={req.is_active}")
        return {"message": "用户创建成功", "user_id": new_user.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建用户失败: {str(e)}")
    finally:
        db.close()


@router.put("/{user_id}")
def update_user(user_id: int, req: UserUpdateRequest, user: AdminUser):
    """管理员：编辑用户（角色/邮箱/描述/启用状态）

    安全约束：不能把自己降级为普通用户或禁用自己，防止锁死系统。
    """
    db = SessionLocal()
    try:
        target = _get_user_or_404(db, user_id)
        is_self = (user_id == user['user_id'])

        if req.role is not None:
            _validate_role(req.role)
            if is_self and req.role != 'admin':
                raise HTTPException(status_code=400, detail="不能将自己的管理员角色降级")
            # 最后一名管理员不能降级
            if target.role == 'admin' and req.role != 'admin' and _count_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="系统至少需要保留一名管理员")
            target.role = req.role

        if req.is_active is not None:
            if req.is_active not in (0, 1):
                raise HTTPException(status_code=400, detail="is_active 只能为 0 或 1")
            if is_self and req.is_active == 0:
                raise HTTPException(status_code=400, detail="不能禁用自己")
            if target.role == 'admin' and req.is_active == 0 and _count_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="系统至少需要保留一名启用的管理员")
            target.is_active = req.is_active

        if req.email is not None:
            target.email = req.email
        if req.description is not None:
            target.description = req.description

        db.commit()
        logger.info(f"管理员 {user['username']} 编辑用户: {target.username}")
        log_audit(user, "update_user",
                  f"target={target.username} role={target.role} is_active={target.is_active}")
        return {"message": "用户信息已更新"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"编辑用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"编辑用户失败: {str(e)}")
    finally:
        db.close()


@router.post("/{user_id}/reset-password")
def reset_user_password(user_id: int, req: ResetPasswordRequest, user: AdminUser):
    """管理员：重置用户密码（强密码策略；pwd_ts 刷新使该用户所有旧 token 失效）"""
    _validate_password_strength(req.new_password)

    import time as _time
    db = SessionLocal()
    try:
        target = _get_user_or_404(db, user_id)
        target.password = hash_password(req.new_password)
        target.pwd_ts = _time.time()
        db.commit()
        logger.info(f"管理员 {user['username']} 重置用户密码: {target.username}")
        log_audit(user, "reset_password", f"target={target.username}")
        return {"message": "密码已重置，该用户旧登录状态已全部失效"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"重置密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置密码失败: {str(e)}")
    finally:
        db.close()


@router.delete("/{user_id}")
def delete_user(user_id: int, user: AdminUser):
    """管理员：删除用户（含其授权、对话、模型配置、知识等关联数据清理）

    安全约束：不能删除自己；不能删除最后一名管理员（建议改为禁用）。
    """
    db = SessionLocal()
    try:
        target = _get_user_or_404(db, user_id)
        if user_id == user['user_id']:
            raise HTTPException(status_code=400, detail="不能删除自己的账号")
        if target.role == 'admin' and _count_admins(db) <= 1:
            raise HTTPException(status_code=400, detail="系统至少需要保留一名管理员，请先禁用该账号")

        uid = target.id
        # 清理外键关联（主库开启 FOREIGN KEY，必须先删子表）
        from models.security import UserColumnGrant, RowScopeRule, QueryAuditLog
        from models.conversation import Conversation, ConversationMessage
        from models.llm import LLMConfig
        from models.knowledge import KnowledgeItem
        from models.sync import DataSource
        from models.user import UserSchemaGrant, UserKnowledgeGrant, UserTableGrant

        # 用户授权（含表级白名单 — 主库外键约束开启，漏删会触发 IntegrityError）
        db.query(UserSchemaGrant).filter(UserSchemaGrant.user_id == uid).delete()
        db.query(UserKnowledgeGrant).filter(UserKnowledgeGrant.user_id == uid).delete()
        db.query(UserTableGrant).filter(UserTableGrant.user_id == uid).delete()
        db.query(UserColumnGrant).filter(UserColumnGrant.user_id == uid).delete()
        db.query(RowScopeRule).filter(RowScopeRule.user_id == uid).delete()
        # 其创建的知识被他人授权时，一并清掉对应授权
        owned_knowledge_ids = [k.id for k in db.query(KnowledgeItem).filter(
            KnowledgeItem.user_id == uid).all()]
        if owned_knowledge_ids:
            db.query(UserKnowledgeGrant).filter(
                UserKnowledgeGrant.knowledge_id.in_(owned_knowledge_ids)).delete()
        db.query(KnowledgeItem).filter(KnowledgeItem.user_id == uid).delete()
        # 对话与消息
        conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.user_id == uid).all()]
        if conv_ids:
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id.in_(conv_ids)).delete()
        db.query(Conversation).filter(Conversation.user_id == uid).delete()
        # 私有模型配置
        db.query(LLMConfig).filter(LLMConfig.user_id == uid).delete()
        # 审计日志（保留管理员删除动作的审计；被删用户的历史查询记录一并清除）
        db.query(QueryAuditLog).filter(QueryAuditLog.user_id == uid).delete()
        # 数据源创建者置空
        db.query(DataSource).filter(DataSource.created_by == uid).update(
            {DataSource.created_by: None})

        log_audit(user, "delete_user", f"target={target.username} user_id={uid}")
        db.delete(target)
        db.commit()
        logger.info(f"管理员 {user['username']} 删除用户: {target.username}")
        return {"message": f"用户 {target.username} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除用户失败: {str(e)}")
    finally:
        db.close()
