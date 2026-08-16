# -*- coding: UTF-8 -*-
"""LLM 路由 — 调用记录（遥测库）+ 模型配置（主库）

调用记录：
- 明细在遥测库 llm_calls，system_prompt 大文本经 llm_prompts 去重存储，
  列表/详情接口通过 LEFT JOIN llm_prompts.content 还原 system_prompt 字段。
模型配置：
- api_key 列存 Fernet 密文（app/security/crypto.py），读取时解密。
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.auth import CurrentUser
from app.logger import logger, log_audit
from app.security.crypto import encrypt_secret, decrypt_secret, mask_api_key
from core.llm import LLMClient
from models import SessionLocal, TelemetrySessionLocal
from models.llm import LLMConfig, LLMCall, LLMPrompt

log_router = APIRouter()
config_router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════════

def _is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


# ═══════════════════════════════════════════════════════════════════
# LLM 调用记录（遥测库）
# ═══════════════════════════════════════════════════════════════════

class LLMLogItem(BaseModel):
    id: int
    user_id: int
    conversation_id: Optional[int] = None
    provider: Optional[str] = None
    question: str
    model: str
    conditions: Optional[str]
    system_prompt: Optional[str] = None
    result: Optional[str]
    duration_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    cost: Optional[float] = None
    status: Optional[str]
    error_message: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class LLMLogListResponse(BaseModel):
    items: List[LLMLogItem]
    total: int


class LLMLogStats(BaseModel):
    total_calls: int
    total_tokens: int
    total_prompt_tokens: int
    total_completion_tokens: int
    avg_duration_ms: float
    success_rate: float
    total_cost: Optional[float] = 0.0


def _call_to_item(call: LLMCall, prompt_content: Optional[str]) -> LLMLogItem:
    return LLMLogItem(
        id=call.id,
        user_id=call.user_id,
        conversation_id=call.conversation_id,
        provider=call.provider,
        question=call.question or '',
        model=call.model,
        conditions=call.conditions,
        system_prompt=prompt_content,
        result=call.result,
        duration_ms=call.duration_ms,
        prompt_tokens=call.prompt_tokens,
        completion_tokens=call.completion_tokens,
        total_tokens=call.total_tokens,
        cost=call.cost,
        status=call.status,
        error_message=call.error_message,
        created_at=call.created_at,
    )


@log_router.get("/list", response_model=LLMLogListResponse)
def get_llm_logs(user: CurrentUser,
                 limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 status: Optional[str] = None):
    """获取LLM调用记录列表（管理员看全部，用户看自己）"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = TelemetrySessionLocal()
    try:
        query = db.query(LLMCall, LLMPrompt.content).outerjoin(
            LLMPrompt, LLMCall.prompt_id == LLMPrompt.id)
        if not is_admin:
            query = query.filter(LLMCall.user_id == user_id)
        if status:
            query = query.filter(LLMCall.status == status)
        total = query.count()
        rows = query.order_by(LLMCall.created_at.desc()).offset(offset).limit(limit).all()
        items = [_call_to_item(c, p) for c, p in rows]
        return LLMLogListResponse(items=items, total=total)
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")
    finally:
        db.close()


@log_router.get("/stats", response_model=LLMLogStats)
def get_llm_stats(user: CurrentUser):
    """获取LLM调用统计（管理员看全部，用户看自己）"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = TelemetrySessionLocal()
    try:
        from sqlalchemy import func

        base = db.query(LLMCall)
        if not is_admin:
            base = base.filter(LLMCall.user_id == user_id)
        total_calls = base.count()

        succ = db.query(LLMCall)
        if not is_admin:
            succ = succ.filter(LLMCall.user_id == user_id)
        success_calls = succ.filter(LLMCall.status == 'success').count()

        sq = db.query(func.sum(LLMCall.total_tokens), func.sum(LLMCall.prompt_tokens),
                      func.sum(LLMCall.completion_tokens), func.avg(LLMCall.duration_ms),
                      func.sum(LLMCall.cost))
        if not is_admin:
            sq = sq.filter(LLMCall.user_id == user_id)
        st = sq.first()
        return LLMLogStats(
            total_calls=total_calls, total_tokens=st[0] or 0,
            total_prompt_tokens=st[1] or 0, total_completion_tokens=st[2] or 0,
            avg_duration_ms=round(st[3] or 0, 2),
            success_rate=round(success_calls / total_calls * 100, 2) if total_calls > 0 else 0,
            total_cost=round(st[4] or 0, 6))
    except Exception as e:
        logger.error(f"获取LLM统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")
    finally:
        db.close()


@log_router.get("/{log_id}", response_model=LLMLogItem)
def get_llm_log(log_id: int, user: CurrentUser):
    """获取单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = TelemetrySessionLocal()
    try:
        row = (db.query(LLMCall, LLMPrompt.content)
               .outerjoin(LLMPrompt, LLMCall.prompt_id == LLMPrompt.id)
               .filter(LLMCall.id == log_id).first())
        if not row:
            raise HTTPException(status_code=404, detail="记录不存在")
        call, prompt_content = row
        if not is_admin and call.user_id != user_id:
            raise HTTPException(status_code=404, detail="记录不存在")
        return _call_to_item(call, prompt_content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")
    finally:
        db.close()


@log_router.delete("/{log_id}")
def delete_llm_log(log_id: int, user: CurrentUser):
    """删除单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = TelemetrySessionLocal()
    try:
        q = db.query(LLMCall).filter(LLMCall.id == log_id)
        if not is_admin:
            q = q.filter(LLMCall.user_id == user_id)
        log = q.first()
        if not log:
            raise HTTPException(status_code=404, detail="记录不存在")
        db.delete(log); db.commit()
        return {"message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# LLM 模型配置（主库，api_key 加密存储）
# ═══════════════════════════════════════════════════════════════════

class LLMConfigCreate(BaseModel):
    provider: str; model: str; api_key: str; base_url: str
    max_tokens: Optional[int] = 8000; temperature: Optional[float] = 0.7
    timeout: Optional[int] = 300; is_default: bool = False
    is_public: bool = False; description: Optional[str] = None


class LLMConfigUpdate(BaseModel):
    model: Optional[str] = None; api_key: Optional[str] = None
    base_url: Optional[str] = None; max_tokens: Optional[int] = None
    temperature: Optional[float] = None; timeout: Optional[int] = None
    is_default: Optional[bool] = None; is_active: Optional[bool] = None
    is_public: Optional[bool] = None; description: Optional[str] = None


class LLMConfigItem(BaseModel):
    id: int; user_id: int; provider: str; model: str; api_key_masked: str
    base_url: Optional[str]; max_tokens: int; temperature: float; timeout: int
    is_default: bool; is_active: bool; is_public: bool
    description: Optional[str]; created_at: Optional[datetime]; updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class LLMConfigListResponse(BaseModel):
    items: List[LLMConfigItem]; total: int


class TestConnectionRequest(BaseModel):
    provider: str; model: str; api_key: Optional[str] = None
    base_url: Optional[str] = None; max_tokens: Optional[int] = 8000
    temperature: Optional[float] = 0.7; config_id: Optional[int] = None


def _get_visible_configs(db, user_id: int):
    return db.query(LLMConfig).filter(
        (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)
    ).order_by(LLMConfig.is_default.desc(), LLMConfig.created_at.desc()).all()


def _get_editable_config(db, config_id: int, user: dict):
    if _is_admin(user):
        return db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    return db.query(LLMConfig).filter(
        LLMConfig.id == config_id, LLMConfig.user_id == user['user_id']).first()


@config_router.get("/list", response_model=LLMConfigListResponse)
def get_configs(user: CurrentUser):
    try:
        db = SessionLocal()
        try:
            configs = _get_visible_configs(db, user['user_id'])
            items = [LLMConfigItem(
                id=c.id, user_id=c.user_id, provider=c.provider, model=c.model,
                api_key_masked=mask_api_key(decrypt_secret(c.api_key)), base_url=c.base_url,
                max_tokens=c.max_tokens or 8000, temperature=c.temperature or 0.7,
                timeout=c.timeout or 300, is_default=c.is_default, is_active=c.is_active,
                is_public=c.is_public or False, description=c.description,
                created_at=c.created_at, updated_at=c.updated_at
            ) for c in configs]
            return LLMConfigListResponse(items=items, total=len(items))
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@config_router.post("/create")
def create_config(request: LLMConfigCreate, user: CurrentUser):
    try:
        user_id = user['user_id']; db = SessionLocal()
        try:
            if request.is_public and not _is_admin(user):
                raise HTTPException(status_code=403, detail="仅管理员可创建公共配置")
            if db.query(LLMConfig).filter(LLMConfig.user_id == user_id,
                    LLMConfig.provider == request.provider, LLMConfig.model == request.model).first():
                raise HTTPException(status_code=400, detail="该供应商+模型已存在配置")
            if request.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == user_id, LLMConfig.is_default == True
                ).update({'is_default': False})
            config = LLMConfig(
                user_id=user_id, provider=request.provider, model=request.model,
                api_key=encrypt_secret(request.api_key), base_url=request.base_url,
                max_tokens=request.max_tokens, temperature=request.temperature,
                timeout=request.timeout, is_default=request.is_default,
                is_public=request.is_public and _is_admin(user), description=request.description)
            db.add(config); db.commit()
            log_audit(user, "create_config", f"{request.provider}/{request.model}")
            return {"message": "配置创建成功", "id": config.id}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@config_router.put("/{config_id}")
def update_config(config_id: int, request: LLMConfigUpdate, user: CurrentUser):
    try:
        db = SessionLocal()
        try:
            config = _get_editable_config(db, config_id, user)
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在或无权修改")
            for attr in ['model', 'base_url', 'max_tokens', 'temperature', 'timeout', 'description']:
                val = getattr(request, attr, None)
                if val is not None:
                    setattr(config, attr, val)
            # api_key 单独处理：非空才覆盖并加密
            if request.api_key is not None and request.api_key != '':
                config.api_key = encrypt_secret(request.api_key)
            if request.is_active is not None:
                config.is_active = request.is_active
            if request.is_public is not None and _is_admin(user):
                config.is_public = request.is_public
            if request.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == config.user_id,
                    LLMConfig.is_default == True, LLMConfig.id != config_id
                ).update({'is_default': False})
                config.is_default = True
            db.commit()
            log_audit(user, "update_config", f"id={config_id}")
            return {"message": "配置更新成功"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@config_router.delete("/{config_id}")
def delete_config(config_id: int, user: CurrentUser):
    try:
        db = SessionLocal()
        try:
            config = _get_editable_config(db, config_id, user)
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在或无权删除")
            db.delete(config); db.commit()
            log_audit(user, "delete_config", f"id={config_id}")
            return {"message": "配置删除成功"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@config_router.post("/test")
def test_connection(request: TestConnectionRequest, user: CurrentUser):
    try:
        api_key = request.api_key; base_url = request.base_url
        if not api_key and request.config_id:
            db = SessionLocal()
            try:
                config = _get_editable_config(db, request.config_id, user)
                if config:
                    api_key = decrypt_secret(config.api_key)
                    base_url = base_url or config.base_url
            finally:
                db.close()
        if not api_key:
            return {"success": False, "message": "API密钥未配置"}
        client = LLMClient(provider=request.provider, api_key=api_key, model=request.model,
                           base_url=base_url, max_tokens=request.max_tokens or 8000)
        return client.test_connection()
    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return {"success": False, "message": f"测试失败: {str(e)}"}


@config_router.post("/set-default/{config_id}")
def set_default_config(config_id: int, user: CurrentUser):
    try:
        user_id = user['user_id']; db = SessionLocal()
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)).first()
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在")
            db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id, LLMConfig.is_default == True
            ).update({'is_default': False})
            config.is_default = True; config.is_active = True; db.commit()
            return {"message": "已设置为默认配置"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


@config_router.get("/default")
def get_default_config(user: CurrentUser):
    try:
        user_id = user['user_id']; db = SessionLocal()
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True, LLMConfig.is_active == True).first()
            if not config:
                return {"has_default": False, "config": None}
            return {"has_default": True, "config": {
                "id": config.id, "provider": config.provider, "model": config.model,
                "api_key_masked": mask_api_key(decrypt_secret(config.api_key)),
                "base_url": config.base_url,
                "max_tokens": config.max_tokens or 8000, "temperature": config.temperature or 0.7,
                "timeout": config.timeout or 300}}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")
