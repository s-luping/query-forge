# -*- coding: UTF-8 -*-
"""
用户相关路由
- 普通用户：修改密码、个人资料
- 管理员：用户管理（列表/创建/分配角色/启用禁用/重置密码/删除）
  角色分配走 /api/permission/users/{user_id}/roles（见 permission_router.py）
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.security import AdminUser, CurrentUser, hash_password, verify_password
from app.limiter import LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit, logger
from app.routers.auth_router import _validate_password_strength
from app.timezone import now_beijing
from crud.base import session_scope
from crud.user import user_crud
from models.role import Role, UserRole
from models.user import User

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    current_password: str
    new_password: str


@router.post("/change-password")
@limiter.limit(LIMIT_WRITE)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: CurrentUser,
):
    """修改用户密码"""
    user_id = current_user['user_id']
    username = current_user['username']

    logger.info(f"用户 {username} 请求修改密码")

    try:
        with session_scope() as db:
            # 获取当前用户
            user = db.query(User).filter(
                User.id == user_id,
                User.username == username
            ).first()

            if not user:
                logger.warning(f"用户不存在: user_id={user_id}, username={username}")
                raise HTTPException(status_code=404, detail="用户不存在")

            # 验证当前密码（bcrypt；历史明文自动升级）
            if not verify_password(payload.current_password, user.password or ''):
                logger.warning(f"用户 {username} 当前密码验证失败")
                raise HTTPException(status_code=400, detail="当前密码不正确")

            # 统一强密码策略
            _validate_password_strength(payload.new_password)

            # 更新密码（哈希）+ 刷新 pwd_ts 使所有旧 token 失效
            import time as _time
            user.password = hash_password(payload.new_password)
            user.pwd_ts = _time.time()
            user.last_login = now_beijing()

        logger.info(f"用户 {username} 密码修改成功")
        log_audit(current_user, "change_password")
        return {"message": "密码修改成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改密码失败: {e}")
        raise HTTPException(status_code=500, detail="修改密码失败，请稍后重试")
    finally:
        db.close()


@router.get("/profile")
@limiter.limit(LIMIT_READ)
async def get_user_profile(request: Request, current_user: CurrentUser):
    """获取用户基本信息"""
    user_id = current_user['user_id']

    with session_scope() as db:
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


# ═══════════════════════════════════════════════════════════════════
# 用户偏好（key-value，如默认勾选的知识库条目）
# ═══════════════════════════════════════════════════════════════════

class DefaultKnowledgeRequest(BaseModel):
    knowledge_ids: list  # 知识条目 id 数组（可空 = 清空默认勾选）


def _validate_knowledge_ids_visible(user: dict, ids: list) -> None:
    """校验知识条目存在且对用户可见（全局/本人创建/授权清单），否则 400"""
    if not ids:
        return
    with session_scope() as db:
        from sqlalchemy import or_
        from models.knowledge import KnowledgeItem
        from app.permissions import get_visible_knowledge_ids
        q = db.query(KnowledgeItem).filter(
            KnowledgeItem.id.in_(ids), KnowledgeItem.is_active == 1)
        visible = get_visible_knowledge_ids(user)
        if visible is not None:
            # 非管理员：全局条目人人可勾选；个人条目属主本人或授权清单内可勾选
            conds = [KnowledgeItem.visibility == 'global',
                     KnowledgeItem.user_id == user['user_id']]
            if visible:
                conds.append(KnowledgeItem.id.in_(visible))
            q = q.filter(or_(*conds))
        found = {row.id for row in q.all()}
    invalid = [i for i in ids if i not in found]
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"知识条目不存在或不可见: {invalid}")


def _get_pref_ids(user_id: int, key: str) -> list:
    """读取用户偏好里的知识 id 列表（缺失返回 []）"""
    from models.preference import UserPreference
    with session_scope() as db:
        row = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
            UserPreference.pref_key == key).first()
        if row:
            from crud.knowledge import _parse_json
            return [int(i) for i in (_parse_json(row.pref_value, []) or []) if i]
    return []


def _set_pref_ids(user_id: int, key: str, ids: list, audit_user: dict, action: str) -> None:
    """写入用户偏好里的知识 id 列表"""
    from models.preference import UserPreference
    with session_scope() as db:
        row = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
            UserPreference.pref_key == key).first()
        if row:
            row.pref_value = json.dumps(ids, ensure_ascii=False)
        else:
            db.add(UserPreference(
                user_id=user_id, pref_key=key,
                pref_value=json.dumps(ids, ensure_ascii=False)))
    log_audit(audit_user, action, f"ids={ids}")


@router.get("/preferences/default-knowledge")
@limiter.limit(LIMIT_READ)
def get_default_knowledge(request: Request, current_user: CurrentUser):
    """获取用户默认勾选的知识库条目 id 列表（新对话自动带上）"""
    return {'knowledge_ids': _get_pref_ids(current_user['user_id'],
                                           'default_knowledge_ids')}


@router.put("/preferences/default-knowledge")
@limiter.limit(LIMIT_WRITE)
def set_default_knowledge(request: Request, body: DefaultKnowledgeRequest,
                          current_user: CurrentUser):
    """设置用户默认勾选的知识库条目（多选；校验条目存在且对用户可见）"""
    ids = [int(i) for i in (body.knowledge_ids or []) if i]
    _validate_knowledge_ids_visible(current_user, ids)
    try:
        _set_pref_ids(current_user['user_id'], 'default_knowledge_ids',
                      ids, current_user, 'set_default_knowledge')
        return {'knowledge_ids': ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 用户自选常驻上限（个人常驻只注入本人对话，条数限制防 prompt 膨胀）
MAX_USER_PINNED_KNOWLEDGE = 20


@router.get("/preferences/pinned-knowledge")
@limiter.limit(LIMIT_READ)
def get_pinned_knowledge(request: Request, current_user: CurrentUser):
    """获取用户自选常驻的知识条目 id 列表（每次对话自动注入，仅本人生效）"""
    return {'knowledge_ids': _get_pref_ids(current_user['user_id'],
                                           'pinned_knowledge_ids')}


@router.put("/preferences/pinned-knowledge")
@limiter.limit(LIMIT_WRITE)
def set_pinned_knowledge(request: Request, body: DefaultKnowledgeRequest,
                         current_user: CurrentUser):
    """设置用户自选常驻的知识条目（每个用户独立，仅注入本人对话）"""
    ids = [int(i) for i in (body.knowledge_ids or []) if i]
    ids = list(dict.fromkeys(ids))   # 去重保序
    if len(ids) > MAX_USER_PINNED_KNOWLEDGE:
        raise HTTPException(status_code=400,
                            detail=f"自选常驻最多 {MAX_USER_PINNED_KNOWLEDGE} 条")
    _validate_knowledge_ids_visible(current_user, ids)
    try:
        _set_pref_ids(current_user['user_id'], 'pinned_knowledge_ids',
                      ids, current_user, 'set_pinned_knowledge')
        return {'knowledge_ids': ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置自选常驻知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════
# 管理员用户管理（AdminUser 依赖：未登录 401 / 非管理员 403）
# ═══════════════════════════════════════════════════════════════════

class UserCreateRequest(BaseModel):
    """管理员创建用户"""
    username: str
    password: str
    email: Optional[str] = None
    description: Optional[str] = None
    is_active: int = 1           # 1=启用 0=禁用


class UserUpdateRequest(BaseModel):
    """管理员更新用户（字段均可选，只更新传入的字段）
    当前前端仅用于启用/禁用（is_active）；邮箱/描述保留接口兼容。"""
    email: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


class ResetPasswordRequest(BaseModel):
    """管理员重置用户密码"""
    new_password: str


def _get_user_or_404(db, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/list")
@limiter.limit(LIMIT_READ)
def list_users(request: Request, user: AdminUser):
    """管理员：用户列表（全字段，含启用状态/注册/最后登录）"""
    with session_scope() as db:
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
@router.post("/create")
@limiter.limit(LIMIT_WRITE)
def create_user(request: Request, req: UserCreateRequest, user: AdminUser):
    """管理员：创建用户；新用户默认绑定 user 角色。"""
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少需要3个字符")
    if req.is_active not in (0, 1):
        raise HTTPException(status_code=400, detail="is_active 只能为 0 或 1")
    _validate_password_strength(req.password)

    import time as _time
    try:
        with session_scope() as db:
            if db.query(User).filter(User.username == req.username).first():
                logger.warning(f"创建用户失败 - 用户名已存在: {req.username}")
                raise HTTPException(status_code=400, detail="用户名已存在")

            new_user = User(
                username=req.username,
                password=hash_password(req.password),
                email=req.email,
                role='user',
                description=req.description,
                is_active=req.is_active,
                pwd_ts=_time.time(),
            )
            db.add(new_user)
            db.flush()
            default_role = db.query(Role).filter(Role.code == 'user').first()
            if default_role:
                db.add(UserRole(user_id=new_user.id, role_id=default_role.id))
        logger.info(f"管理员 {user['username']} 创建用户: {req.username}")
        log_audit(user, "create_user",
                  f"target={req.username} is_active={req.is_active}")
        return {"message": "用户创建成功", "user_id": new_user.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建用户失败: {str(e)}")


@router.put("/{user_id}")
@limiter.limit(LIMIT_WRITE)
def update_user(request: Request, user_id: int, req: UserUpdateRequest, user: AdminUser):
    """管理员：更新用户（当前前端仅用于启用/禁用；角色分配见 permission_router）。"""
    try:
        with session_scope() as db:
            target = _get_user_or_404(db, user_id)
            is_self = (user_id == user['user_id'])

            if req.is_active is not None:
                if req.is_active not in (0, 1):
                    raise HTTPException(status_code=400, detail="is_active 只能为 0 或 1")
                if is_self and req.is_active == 0:
                    raise HTTPException(status_code=400, detail="不能禁用自己")
                if target.role == 'admin' and req.is_active == 0 and user_crud.count_admins() <= 1:
                    raise HTTPException(status_code=400, detail="系统至少需要保留一名启用的管理员")
                target.is_active = req.is_active

            if req.email is not None:
                target.email = req.email
            if req.description is not None:
                target.description = req.description
        logger.info(f"管理员 {user['username']} 编辑用户: {target.username}")
        log_audit(user, "update_user",
              f"target={target.username} is_active={target.is_active}")
        return {"message": "用户信息已更新"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"编辑用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"编辑用户失败: {str(e)}")


@router.post("/{user_id}/reset-password")
@limiter.limit(LIMIT_WRITE)
def reset_user_password(request: Request, user_id: int, req: ResetPasswordRequest, user: AdminUser):
    """管理员：重置用户密码（强密码策略；pwd_ts 刷新使该用户所有旧 token 失效）"""
    _validate_password_strength(req.new_password)

    import time as _time
    try:
        with session_scope() as db:
            target = _get_user_or_404(db, user_id)
            target.password = hash_password(req.new_password)
            target.pwd_ts = _time.time()
            # 会话关闭后 target 已过期+脱离，日志要用的属性先取出
            target_username = target.username
        logger.info(f"管理员 {user['username']} 重置用户密码: {target_username}")
        log_audit(user, "reset_password", f"target={target_username}")
        return {"message": "密码已重置，该用户旧登录状态已全部失效"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置密码失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置密码失败: {str(e)}")


@router.delete("/{user_id}")
@limiter.limit(LIMIT_WRITE)
def delete_user(request: Request, user_id: int, user: AdminUser):
    """管理员：删除用户（含其授权、对话、模型配置、知识等关联数据清理）

    安全约束：不能删除自己；不能删除最后一名管理员（建议改为禁用）。
    """
    try:
        with session_scope() as db:
            target = _get_user_or_404(db, user_id)
            if user_id == user['user_id']:
                raise HTTPException(status_code=400, detail="不能删除自己的账号")
            if target.role == 'admin' and user_crud.count_admins() <= 1:
                raise HTTPException(status_code=400, detail="系统至少需要保留一名管理员，请先禁用该账号")

            uid = target.id
            # 清理外键关联（主库开启 FOREIGN KEY，必须先删子表）
            from models.conversation import Conversation, ConversationMessage
            from models.datasource import DataSource
            from models.knowledge import KnowledgeItem
            from models.llm import LLMConfig
            from models.role import UserRole
            from models.security import QueryAuditLog
            db.query(UserRole).filter(UserRole.user_id == uid).delete()            # 其创建的知识由角色资源权限引用时，一并清理相关授权
            owned_knowledge_ids = [k.id for k in db.query(KnowledgeItem).filter(
                KnowledgeItem.user_id == uid).all()]
            if owned_knowledge_ids:
                from models.role import RolePermission
                db.query(RolePermission).filter(
                    RolePermission.resource_type == 'knowledge',
                    RolePermission.resource_id.in_(owned_knowledge_ids)).delete()
            db.query(KnowledgeItem).filter(KnowledgeItem.user_id == uid).delete()
            # 对话与消息
            conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.user_id == uid).all()]
            if conv_ids:
                db.query(ConversationMessage).filter(
                    ConversationMessage.conversation_id.in_(conv_ids)).delete()
            db.query(Conversation).filter(Conversation.user_id == uid).delete()
            # 私有模型配置
            db.query(LLMConfig).filter(LLMConfig.user_id == uid).delete()
            # 数据源创建者置空
            db.query(DataSource).filter(DataSource.created_by == uid).update(
                {DataSource.created_by: None})

            db.delete(target)
            # 会话关闭后 target 已过期+脱离，日志要用的属性先取出
            target_username = target.username
        # 审计日志在日志库（跨库无外键，主库事务提交后单独清理；
        # 保留管理员删除动作的审计，被删用户的历史查询记录一并清除）
        with session_scope(logs=True) as ldb:
            ldb.query(QueryAuditLog).filter(QueryAuditLog.user_id == uid).delete()
        log_audit(user, "delete_user", f"target={target_username} user_id={uid}")
        logger.info(f"管理员 {user['username']} 删除用户: {target_username}")
        return {"message": f"用户 {target_username} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除用户失败: {str(e)}")
