# -*- coding: UTF-8 -*-
"""
LLM配置管理路由
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.logger import logger
from app.auth import get_current_user
from models import AppSessionLocal
from models.llm_config import LLMConfig
from core.LLMClient import LLMClient


router = APIRouter()


class LLMConfigCreate(BaseModel):
    """创建LLM配置请求"""
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None
    max_tokens: Optional[int] = 8000
    temperature: Optional[float] = 0.7
    timeout: Optional[int] = 300
    is_default: bool = False
    description: Optional[str] = None


class LLMConfigUpdate(BaseModel):
    """更新LLM配置请求"""
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class LLMConfigItem(BaseModel):
    """LLM配置项"""
    id: int
    provider: str
    model: str
    api_key_masked: str
    base_url: Optional[str]
    max_tokens: int
    temperature: float
    timeout: int
    is_default: bool
    is_active: bool
    description: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class LLMConfigListResponse(BaseModel):
    """LLM配置列表响应"""
    items: List[LLMConfigItem]
    total: int


class ProviderInfo(BaseModel):
    """模型提供商信息"""
    provider: str
    name: str
    default_model: str
    models: List[str]


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: Optional[int] = 8000
    temperature: Optional[float] = 0.7
    config_id: Optional[int] = None


@router.get("/providers", response_model=List[ProviderInfo])
async def get_providers():
    """获取支持的模型提供商列表"""
    providers = LLMClient.get_supported_providers()
    return [ProviderInfo(**p) for p in providers]


@router.get("/list", response_model=LLMConfigListResponse)
async def get_configs(
    user = Depends(get_current_user)
):
    """获取用户的LLM配置列表"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            configs = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id
            ).order_by(LLMConfig.is_default.desc(), LLMConfig.created_at.desc()).all()
            
            items = []
            for config in configs:
                api_key_masked = mask_api_key(config.api_key)
                items.append(LLMConfigItem(
                    id=config.id,
                    provider=config.provider,
                    model=config.model,
                    api_key_masked=api_key_masked,
                    base_url=config.base_url,
                    max_tokens=config.max_tokens or 8000,
                    temperature=config.temperature or 0.7,
                    timeout=config.timeout or 300,
                    is_default=config.is_default,
                    is_active=config.is_active,
                    description=config.description,
                    created_at=config.created_at,
                    updated_at=config.updated_at
                ))
            
            return LLMConfigListResponse(items=items, total=len(items))
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/create")
async def create_config(
    request: LLMConfigCreate,
    user = Depends(get_current_user)
):
    """创建LLM配置"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            existing = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.provider == request.provider
            ).first()
            
            if existing:
                raise HTTPException(status_code=400, detail="该模型提供商已存在配置，请使用编辑功能")
            
            if request.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == user_id,
                    LLMConfig.is_default == True
                ).update({'is_default': False})
            
            config = LLMConfig(
                user_id=user_id,
                provider=request.provider,
                model=request.model,
                api_key=request.api_key,
                base_url=request.base_url,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                timeout=request.timeout,
                is_default=request.is_default,
                description=request.description
            )
            db.add(config)
            db.commit()
            
            return {"message": "配置创建成功", "id": config.id}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@router.put("/{config_id}")
async def update_config(
    config_id: int,
    request: LLMConfigUpdate,
    user = Depends(get_current_user)
):
    """更新LLM配置"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.user_id == user_id
            ).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在")
            
            if request.model is not None:
                config.model = request.model
            if request.api_key is not None:
                config.api_key = request.api_key
            if request.base_url is not None:
                config.base_url = request.base_url
            if request.max_tokens is not None:
                config.max_tokens = request.max_tokens
            if request.temperature is not None:
                config.temperature = request.temperature
            if request.timeout is not None:
                config.timeout = request.timeout
            if request.is_active is not None:
                config.is_active = request.is_active
            if request.description is not None:
                config.description = request.description
            
            if request.is_default:
                db.query(LLMConfig).filter(
                    LLMConfig.user_id == user_id,
                    LLMConfig.is_default == True,
                    LLMConfig.id != config_id
                ).update({'is_default': False})
                config.is_default = True
            
            db.commit()
            
            return {"message": "配置更新成功"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.delete("/{config_id}")
async def delete_config(
    config_id: int,
    user = Depends(get_current_user)
):
    """删除LLM配置"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.user_id == user_id
            ).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在")
            
            db.delete(config)
            db.commit()
            
            return {"message": "配置删除成功"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除LLM配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.post("/test")
async def test_connection(
    request: TestConnectionRequest,
    user = Depends(get_current_user)
):
    """测试API连接"""
    try:
        user_id = user['user_id']
        api_key = request.api_key
        base_url = request.base_url
        
        if not api_key and request.config_id:
            db = AppSessionLocal()
            try:
                config = db.query(LLMConfig).filter(
                    LLMConfig.id == request.config_id,
                    LLMConfig.user_id == user_id
                ).first()
                if config:
                    api_key = config.api_key
                    if not base_url:
                        base_url = config.base_url
            finally:
                db.close()
        
        if not api_key:
            return {"success": False, "message": "API密钥未配置"}
        
        client = LLMClient(
            provider=request.provider,
            api_key=api_key,
            model=request.model,
            max_tokens=request.max_tokens or 8000
        )
        
        if base_url:
            client.base_url = base_url
        
        result = client.test_connection()
        return result
        
    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return {"success": False, "message": f"测试失败: {str(e)}"}


@router.post("/set-default/{config_id}")
async def set_default_config(
    config_id: int,
    user = Depends(get_current_user)
):
    """设置默认配置"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.user_id == user_id
            ).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="配置不存在")
            
            db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True
            ).update({'is_default': False})
            
            config.is_default = True
            config.is_active = True
            db.commit()
            
            return {"message": "已设置为默认配置"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


@router.get("/default")
async def get_default_config(
    user = Depends(get_current_user)
):
    """获取用户的默认配置"""
    try:
        user_id = user['user_id']
        db = AppSessionLocal()
        
        try:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True,
                LLMConfig.is_active == True
            ).first()
            
            if not config:
                return {"has_default": False, "config": None}
            
            return {
                "has_default": True,
                "config": {
                    "id": config.id,
                    "provider": config.provider,
                    "model": config.model,
                    "api_key_masked": mask_api_key(config.api_key),
                    "base_url": config.base_url,
                    "max_tokens": config.max_tokens or 8000,
                    "temperature": config.temperature or 0.7,
                    "timeout": config.timeout or 300
                }
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取默认配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


def mask_api_key(api_key: str) -> str:
    """遮蔽API密钥"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]
