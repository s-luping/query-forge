# -*- coding: UTF-8 -*-
"""LLM 路由 — 调用记录（遥测库）+ 模型配置（主库）

调用记录：
- 明细在遥测库 llm_calls，system_prompt 大文本经 llm_prompts 去重存储，
  列表/详情接口通过 LEFT JOIN llm_prompts.content 还原 system_prompt 字段。
模型配置：
- api_key 列存 Fernet 密文（app/security/crypto.py），读取时解密。
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import CurrentUser
from app.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.limiter import LIMIT_READ, LIMIT_TEST, LIMIT_WRITE, limiter
from app.logger import log_audit, logger
from app.response import ErrorCode, fail
from core import LLMClient
from crud.base import session_scope
from models.llm import LLMCall, LLMConfig, LLMPrompt

log_router = APIRouter()
config_router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════════

def _is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def _apply_log_filters(query, user_id: int, is_admin: bool,
                       status: Optional[str] = None, provider: Optional[str] = None,
                       model: Optional[str] = None, days: Optional[int] = None,
                       min_duration_ms: Optional[float] = None,
                       min_tokens: Optional[int] = None):
    """调用记录筛选条件（/list 与 /stats 共用）。days: 1=今天 7=近一周 30=近30天"""
    if not is_admin:
        query = query.filter(LLMCall.user_id == user_id)
    if status:
        query = query.filter(LLMCall.status == status)
    if provider:
        query = query.filter(LLMCall.provider == provider)
    if model:
        query = query.filter(LLMCall.model == model)
    if days:
        if days == 1:
            start = datetime.combine(datetime.now().date(), datetime.min.time())
        else:
            start = datetime.now() - timedelta(days=days)
        query = query.filter(LLMCall.created_at >= start)
    if min_duration_ms is not None:
        query = query.filter(LLMCall.duration_ms >= min_duration_ms)
    if min_tokens is not None:
        query = query.filter(LLMCall.total_tokens >= min_tokens)
    return query


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
    reasoning_tokens: Optional[int] = 0
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
        reasoning_tokens=call.reasoning_tokens,
        total_tokens=call.total_tokens,
        cost=call.cost,
        status=call.status,
        error_message=call.error_message,
        created_at=call.created_at,
    )


@log_router.get("/list", response_model=LLMLogListResponse)
@limiter.limit(LIMIT_READ)
def get_llm_logs(request: Request, user: CurrentUser,
                 limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 status: Optional[str] = None, provider: Optional[str] = None,
                 model: Optional[str] = None,
                 days: Optional[int] = Query(None, ge=1, le=365),
                 min_duration_ms: Optional[float] = Query(None, ge=0),
                 min_tokens: Optional[int] = Query(None, ge=0)):
    """获取LLM调用记录列表（管理员看全部，用户看自己），支持状态/供应商/模型/日期/耗时/Token筛选"""
    try:
        with session_scope(telemetry=True) as db:
            query = db.query(LLMCall, LLMPrompt.content).outerjoin(
                LLMPrompt, LLMCall.prompt_id == LLMPrompt.id)
            query = _apply_log_filters(query, user['user_id'], _is_admin(user),
                                       status=status, provider=provider, model=model,
                                       days=days, min_duration_ms=min_duration_ms,
                                       min_tokens=min_tokens)
            total = query.count()
            rows = query.order_by(LLMCall.created_at.desc()).offset(offset).limit(limit).all()
            items = [_call_to_item(c, p) for c, p in rows]
            return LLMLogListResponse(items=items, total=total)
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")


@log_router.get("/stats", response_model=LLMLogStats)
@limiter.limit(LIMIT_READ)
def get_llm_stats(request: Request, user: CurrentUser,
                  status: Optional[str] = None, provider: Optional[str] = None,
                  model: Optional[str] = None,
                  days: Optional[int] = Query(None, ge=1, le=365),
                  min_duration_ms: Optional[float] = Query(None, ge=0),
                  min_tokens: Optional[int] = Query(None, ge=0)):
    """获取LLM调用统计（管理员看全部，用户看自己），筛选条件与 /list 一致"""
    try:
        with session_scope(telemetry=True) as db:
            from sqlalchemy import func

            base = db.query(LLMCall)
            base = _apply_log_filters(base, user['user_id'], _is_admin(user),
                                      status=status, provider=provider, model=model,
                                      days=days, min_duration_ms=min_duration_ms,
                                      min_tokens=min_tokens)
            total_calls = base.count()

            succ = db.query(LLMCall)
            succ = _apply_log_filters(succ, user['user_id'], _is_admin(user),
                                      status='success', provider=provider, model=model,
                                      days=days, min_duration_ms=min_duration_ms,
                                      min_tokens=min_tokens)
            success_calls = succ.count()

            sq = db.query(func.sum(LLMCall.total_tokens), func.sum(LLMCall.prompt_tokens),
                          func.sum(LLMCall.completion_tokens), func.avg(LLMCall.duration_ms),
                          func.sum(LLMCall.cost))
            sq = _apply_log_filters(sq, user['user_id'], _is_admin(user),
                                    status=status, provider=provider, model=model,
                                    days=days, min_duration_ms=min_duration_ms,
                                    min_tokens=min_tokens)
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


@log_router.get("/filter-options")
@limiter.limit(LIMIT_READ)
def get_filter_options(request: Request, user: CurrentUser):
    """筛选下拉框可选项：当前可见范围内的去重供应商/模型列表"""
    try:
        with session_scope(telemetry=True) as db:
            base = db.query(LLMCall)
            if not _is_admin(user):
                base = base.filter(LLMCall.user_id == user['user_id'])
            rows = base.with_entities(LLMCall.provider, LLMCall.model).distinct().all()
            providers = sorted({r[0] for r in rows if r[0]})
            models = sorted({r[1] for r in rows if r[1]})
            return {'providers': providers, 'models': models}
    except Exception as e:
        logger.error(f"获取筛选可选项失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取筛选项失败: {str(e)}")


@log_router.get("/{log_id}", response_model=LLMLogItem)
@limiter.limit(LIMIT_READ)
def get_llm_log(request: Request, log_id: int, user: CurrentUser):
    """获取单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    try:
        with session_scope(telemetry=True) as db:
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


@log_router.delete("/{log_id}")
@limiter.limit(LIMIT_WRITE)
def delete_llm_log(request: Request, log_id: int, user: CurrentUser):
    """删除单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    try:
        with session_scope(telemetry=True) as db:
            q = db.query(LLMCall).filter(LLMCall.id == log_id)
            if not is_admin:
                q = q.filter(LLMCall.user_id == user_id)
            log = q.first()
            if not log:
                raise HTTPException(status_code=404, detail="记录不存在")
            db.delete(log)
            return {"message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
# LLM 模型配置（主库，api_key 加密存储）
# ═══════════════════════════════════════════════════════════════════

_THINKING_MODES = ('auto', 'enabled', 'disabled')
_STATUS_VALUES = ('normal', 'arrears')


class LLMConfigCreate(BaseModel):
    provider: str; model: str; api_key: str; base_url: str
    max_tokens: Optional[int] = 8192; temperature: Optional[float] = 0.0
    thinking_mode: Optional[str] = 'auto'
    timeout: Optional[int] = 300; is_default: bool = False
    is_public: bool = False; description: Optional[str] = None


class LLMConfigUpdate(BaseModel):
    model: Optional[str] = None; api_key: Optional[str] = None
    base_url: Optional[str] = None; max_tokens: Optional[int] = None
    temperature: Optional[float] = None; thinking_mode: Optional[str] = None
    timeout: Optional[int] = None
    is_default: Optional[bool] = None; is_active: Optional[bool] = None
    is_public: Optional[bool] = None; description: Optional[str] = None
    status: Optional[str] = None   # normal=正常 / arrears=欠费（续费后手动恢复用）


class LLMConfigItem(BaseModel):
    id: int; user_id: int; provider: str; model: str; api_key_masked: str
    base_url: Optional[str]; max_tokens: int; temperature: float; timeout: int
    thinking_mode: str = 'auto'
    is_default: bool; is_active: bool; is_public: bool
    status: str = 'normal'
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
@limiter.limit(LIMIT_READ)
def get_configs(request: Request, user: CurrentUser):
    try:
        with session_scope() as db:
            configs = _get_visible_configs(db, user['user_id'])
            items = [LLMConfigItem(
                id=c.id, user_id=c.user_id, provider=c.provider, model=c.model,
                api_key_masked=mask_api_key(decrypt_secret(c.api_key)), base_url=c.base_url,
                max_tokens=c.max_tokens if c.max_tokens is not None else 8192,
                temperature=c.temperature if c.temperature is not None else 0.0,
                timeout=c.timeout or 300, thinking_mode=c.thinking_mode or 'auto',
                is_default=c.is_default, is_active=c.is_active,
                is_public=c.is_public or False, status=c.status or 'normal',
                description=c.description,
                created_at=c.created_at, updated_at=c.updated_at
            ) for c in configs]
            return LLMConfigListResponse(items=items, total=len(items))
    except Exception as e:
        logger.error(f"获取LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@config_router.post("/create")
@limiter.limit(LIMIT_WRITE)
def create_config(request: Request, payload: LLMConfigCreate, user: CurrentUser):
    try:
        user_id = user['user_id']
        with session_scope() as db:
            if payload.is_public and not _is_admin(user):
                raise HTTPException(status_code=403, detail="仅管理员可创建公共配置")
            if payload.thinking_mode not in _THINKING_MODES:
                raise HTTPException(status_code=400, detail="thinking_mode 仅支持 auto/enabled/disabled")
            if db.query(LLMConfig).filter(LLMConfig.user_id == user_id,
                    LLMConfig.provider == payload.provider, LLMConfig.model == payload.model).first():
                raise HTTPException(status_code=400, detail="该供应商+模型已存在配置")
            if payload.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == user_id, LLMConfig.is_default == True
                ).update({'is_default': False})
            config = LLMConfig(
                user_id=user_id, provider=payload.provider, model=payload.model,
                api_key=encrypt_secret(payload.api_key), base_url=payload.base_url,
                max_tokens=payload.max_tokens, temperature=payload.temperature,
                thinking_mode=payload.thinking_mode or 'auto',
                timeout=payload.timeout, is_default=payload.is_default,
                is_public=payload.is_public and _is_admin(user), description=payload.description)
            db.add(config)
            db.flush()   # 立即取回自增 id
            log_audit(user, "create_config", f"{payload.provider}/{payload.model}")
            return {"message": "配置创建成功", "id": config.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@config_router.put("/{config_id}")
@limiter.limit(LIMIT_WRITE)
def update_config(request: Request, config_id: int, payload: LLMConfigUpdate, user: CurrentUser):
    try:
        with session_scope() as db:
            config = _get_editable_config(db, config_id, user)
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在或无权修改")
            if payload.thinking_mode is not None and payload.thinking_mode not in _THINKING_MODES:
                raise HTTPException(status_code=400, detail="thinking_mode 仅支持 auto/enabled/disabled")
            if payload.status is not None and payload.status not in _STATUS_VALUES:
                raise HTTPException(status_code=400, detail="status 仅支持 normal/arrears")
            # 注意：必须读 payload 而非 request — Starlette Request 自带 base_url 属性
            # （URL 对象），误读会把请求地址写进库导致 sqlite3.InterfaceError
            for attr in ['model', 'base_url', 'max_tokens', 'temperature', 'thinking_mode',
                         'timeout', 'description', 'status']:
                val = getattr(payload, attr, None)
                if val is not None:
                    if attr == 'base_url':
                        val = str(val)   # 防御：杜绝 URL 等非 str 对象写入 String 列
                    setattr(config, attr, val)
            # api_key 单独处理：非空才覆盖并加密
            if payload.api_key is not None and payload.api_key != '':
                config.api_key = encrypt_secret(payload.api_key)
            if payload.is_active is not None:
                config.is_active = payload.is_active
            if payload.is_public is not None and _is_admin(user):
                config.is_public = payload.is_public
            if payload.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == config.user_id,
                    LLMConfig.is_default == True, LLMConfig.id != config_id
                ).update({'is_default': False})
                config.is_default = True
            log_audit(user, "update_config", f"id={config_id}")
            return {"message": "配置更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@config_router.delete("/{config_id}")
@limiter.limit(LIMIT_WRITE)
def delete_config(request: Request, config_id: int, user: CurrentUser):
    try:
        with session_scope() as db:
            config = _get_editable_config(db, config_id, user)
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在或无权删除")
            db.delete(config)
            log_audit(user, "delete_config", f"id={config_id}")
            return {"message": "配置删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@config_router.post("/test")
@limiter.limit(LIMIT_TEST)
def test_connection(request: Request, payload: TestConnectionRequest, user: CurrentUser):
    try:
        api_key = payload.api_key; base_url = payload.base_url
        if not api_key and payload.config_id:
            with session_scope() as db:
                config = _get_editable_config(db, payload.config_id, user)
                if config:
                    api_key = decrypt_secret(config.api_key)
                    base_url = base_url or config.base_url
        if not api_key:
            return fail(ErrorCode.BAD_REQUEST, "API密钥未配置")
        client = LLMClient(provider=payload.provider, api_key=api_key, model=payload.model,
                           base_url=base_url, max_tokens=payload.max_tokens or 8000)
        return client.test_connection()
    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return fail(ErrorCode.INTERNAL, f"测试失败: {str(e)}")


@config_router.post("/set-default/{config_id}")
@limiter.limit(LIMIT_WRITE)
def set_default_config(request: Request, config_id: int, user: CurrentUser):
    try:
        user_id = user['user_id']
        with session_scope() as db:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)).first()
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在")
            db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id, LLMConfig.is_default == True
            ).update({'is_default': False})
            config.is_default = True; config.is_active = True
            return {"message": "已设置为默认配置"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


@config_router.get("/default")
@limiter.limit(LIMIT_READ)
def get_default_config(request: Request, user: CurrentUser):
    try:
        user_id = user['user_id']
        with session_scope() as db:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True, LLMConfig.is_active == True).first()
            if not config:
                return {"has_default": False, "config": None}
            return {"has_default": True, "config": {
                "id": config.id, "provider": config.provider, "model": config.model,
                "api_key_masked": mask_api_key(decrypt_secret(config.api_key)),
                "base_url": config.base_url,
                "max_tokens": config.max_tokens if config.max_tokens is not None else 8192,
                "temperature": config.temperature if config.temperature is not None else 0.0,
                "thinking_mode": config.thinking_mode or 'auto',
                "timeout": config.timeout or 300}}
    except Exception as e:
        logger.error(f"获取默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")
