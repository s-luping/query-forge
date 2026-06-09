"""LLM 路由 — 调用记录 + 模型配置"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from app.auth import get_current_user
from app.logger import logger, log_audit
from core.LLMClient import LLMClient
from models import AppSessionLocal, LLMSessionLocal
from models.llm import LLMLog, LLMConfig

log_router = APIRouter()
config_router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════════════

def _is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def mask_api_key(api_key: str) -> str:
    if not api_key: return ""
    if len(api_key) <= 8: return "****"
    return api_key[:4] + "****" + api_key[-4:]


# ═══════════════════════════════════════════════════════════════════
# LLM 调用记录
# ═══════════════════════════════════════════════════════════════════

class LLMLogItem(BaseModel):
    id: int
    user_id: int
    conversation_id: Optional[int] = None
    provider: Optional[str] = None
    question: str
    model: str
    conditions: Optional[str]
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


@log_router.get("/list", response_model=LLMLogListResponse)
def get_llm_logs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 status: Optional[str] = None, user=Depends(get_current_user)):
    """获取LLM调用记录列表（管理员看全部，用户看自己）"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = LLMSessionLocal()
    try:
        query = db.query(LLMLog)
        if not is_admin: query = query.filter(LLMLog.user_id == user_id)
        if status: query = query.filter(LLMLog.status == status)
        total = query.count()
        items = query.order_by(LLMLog.created_at.desc()).offset(offset).limit(limit).all()
        return LLMLogListResponse(items=[LLMLogItem.model_validate(i) for i in items], total=total)
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")
    finally:
        db.close()


@log_router.get("/stats", response_model=LLMLogStats)
def get_llm_stats(user=Depends(get_current_user)):
    """获取LLM调用统计（管理员看全部，用户看自己）"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = LLMSessionLocal()
    try:
        base = db.query(LLMLog)
        if not is_admin: base = base.filter(LLMLog.user_id == user_id)
        total_calls = base.count()
        succ = db.query(LLMLog)
        if not is_admin: succ = succ.filter(LLMLog.user_id == user_id)
        success_calls = succ.filter(LLMLog.status == 'success').count()
        from sqlalchemy import func
        sq = db.query(func.sum(LLMLog.total_tokens), func.sum(LLMLog.prompt_tokens),
                      func.sum(LLMLog.completion_tokens), func.avg(LLMLog.duration_ms),
                      func.sum(LLMLog.cost))
        if not is_admin: sq = sq.filter(LLMLog.user_id == user_id)
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
def get_llm_log(log_id: int, user=Depends(get_current_user)):
    """获取单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = LLMSessionLocal()
    try:
        q = db.query(LLMLog).filter(LLMLog.id == log_id)
        if not is_admin: q = q.filter(LLMLog.user_id == user_id)
        log = q.first()
        if not log: raise HTTPException(status_code=404, detail="记录不存在")
        return LLMLogItem.model_validate(log)
    except HTTPException: raise
    except Exception as e:
        logger.error(f"获取LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记录失败: {str(e)}")
    finally:
        db.close()


@log_router.delete("/{log_id}")
def delete_llm_log(log_id: int, user=Depends(get_current_user)):
    """删除单条LLM调用记录"""
    user_id = user['user_id']; is_admin = user.get('role') == 'admin'
    db = LLMSessionLocal()
    try:
        q = db.query(LLMLog).filter(LLMLog.id == log_id)
        if not is_admin: q = q.filter(LLMLog.user_id == user_id)
        log = q.first()
        if not log: raise HTTPException(status_code=404, detail="记录不存在")
        db.delete(log); db.commit()
        return {"message": "删除成功"}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"删除LLM调用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# LLM 模型配置
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
    class Config: from_attributes = True


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
    return db.query(LLMConfig).filter(LLMConfig.id == config_id, LLMConfig.user_id == user['user_id']).first()


@config_router.get("/list", response_model=LLMConfigListResponse)
def get_configs(user=Depends(get_current_user)):
    try:
        db = AppSessionLocal()
        try:
            configs = _get_visible_configs(db, user['user_id'])
            items = [LLMConfigItem(
                id=c.id, user_id=c.user_id, provider=c.provider, model=c.model,
                api_key_masked=mask_api_key(c.api_key), base_url=c.base_url,
                max_tokens=c.max_tokens or 8000, temperature=c.temperature or 0.7,
                timeout=c.timeout or 300, is_default=c.is_default, is_active=c.is_active,
                is_public=c.is_public or False, description=c.description,
                created_at=c.created_at, updated_at=c.updated_at
            ) for c in configs]
            return LLMConfigListResponse(items=items, total=len(items))
        finally: db.close()
    except Exception as e:
        logger.error(f"获取LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@config_router.post("/create")
def create_config(request: LLMConfigCreate, user=Depends(get_current_user)):
    try:
        user_id = user['user_id']; db = AppSessionLocal()
        try:
            if request.is_public and not _is_admin(user):
                raise HTTPException(status_code=403, detail="仅管理员可创建公共配置")
            if db.query(LLMConfig).filter(LLMConfig.user_id == user_id,
                    LLMConfig.provider == request.provider, LLMConfig.model == request.model).first():
                raise HTTPException(status_code=400, detail="该供应商+模型已存在配置")
            if request.is_default:
                db.query(LLMConfig).filter(LLMConfig.user_id == user_id, LLMConfig.is_default == True
                    ).update({'is_default': False})
            config = LLMConfig(user_id=user_id, provider=request.provider, model=request.model,
                api_key=request.api_key, base_url=request.base_url, max_tokens=request.max_tokens,
                temperature=request.temperature, timeout=request.timeout, is_default=request.is_default,
                is_public=request.is_public and _is_admin(user), description=request.description)
            db.add(config); db.commit()
            log_audit(user, "create_config", f"{request.provider}/{request.model}")
            return {"message": "配置创建成功", "id": config.id}
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"创建LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@config_router.put("/{config_id}")
def update_config(config_id: int, request: LLMConfigUpdate, user=Depends(get_current_user)):
    try:
        db = AppSessionLocal()
        try:
            config = _get_editable_config(db, config_id, user)
            if not config: raise HTTPException(status_code=404, detail="配置不存在或无权修改")
            for attr in ['model','api_key','base_url','max_tokens','temperature','timeout','description']:
                val = getattr(request, attr, None)
                if val is not None: setattr(config, attr, val)
            if request.is_active is not None: config.is_active = request.is_active
            if request.is_public is not None and _is_admin(user): config.is_public = request.is_public
            if request.is_default:
                db.query(LLMConfig).filter(LLMConfig.user_id == config.user_id,
                    LLMConfig.is_default == True, LLMConfig.id != config_id).update({'is_default': False})
                config.is_default = True
            db.commit()
            log_audit(user, "update_config", f"id={config_id}")
            return {"message": "配置更新成功"}
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"更新LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@config_router.delete("/{config_id}")
def delete_config(config_id: int, user=Depends(get_current_user)):
    try:
        db = AppSessionLocal()
        try:
            config = _get_editable_config(db, config_id, user)
            if not config: raise HTTPException(status_code=404, detail="配置不存在或无权删除")
            db.delete(config); db.commit()
            log_audit(user, "delete_config", f"id={config_id}")
            return {"message": "配置删除成功"}
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"删除LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@config_router.post("/test")
def test_connection(request: TestConnectionRequest, user=Depends(get_current_user)):
    try:
        api_key = request.api_key; base_url = request.base_url
        if not api_key and request.config_id:
            db = AppSessionLocal()
            try:
                config = _get_editable_config(db, request.config_id, user)
                if config: api_key = config.api_key; base_url = base_url or config.base_url
            finally: db.close()
        if not api_key: return {"success": False, "message": "API密钥未配置"}
        client = LLMClient(provider=request.provider, api_key=api_key, model=request.model,
                           base_url=base_url, max_tokens=request.max_tokens or 8000)
        return client.test_connection()
    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return {"success": False, "message": f"测试失败: {str(e)}"}


@config_router.post("/set-default/{config_id}")
def set_default_config(config_id: int, user=Depends(get_current_user)):
    try:
        user_id = user['user_id']; db = AppSessionLocal()
        try:
            config = db.query(LLMConfig).filter(LLMConfig.id == config_id,
                (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)).first()
            if not config: raise HTTPException(status_code=404, detail="配置不存在")
            db.query(LLMConfig).filter(LLMConfig.user_id == user_id, LLMConfig.is_default == True
                ).update({'is_default': False})
            config.is_default = True; config.is_active = True; db.commit()
            return {"message": "已设置为默认配置"}
        finally: db.close()
    except HTTPException: raise
    except Exception as e:
        logger.error(f"设置默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


@config_router.get("/default")
def get_default_config(user=Depends(get_current_user)):
    try:
        user_id = user['user_id']; db = AppSessionLocal()
        try:
            config = db.query(LLMConfig).filter(LLMConfig.user_id == user_id,
                LLMConfig.is_default == True, LLMConfig.is_active == True).first()
            if not config: return {"has_default": False, "config": None}
            return {"has_default": True, "config": {
                "id": config.id, "provider": config.provider, "model": config.model,
                "api_key_masked": mask_api_key(config.api_key), "base_url": config.base_url,
                "max_tokens": config.max_tokens or 8000, "temperature": config.temperature or 0.7,
                "timeout": config.timeout or 300}}
        finally: db.close()
    except Exception as e:
        logger.error(f"获取默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")
