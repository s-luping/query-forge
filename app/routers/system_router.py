# -*- coding: UTF-8 -*-
"""系统配置路由 — 系统参数、embedding 状态

配置存储于 SystemSetting 表（models/system.py），分类见 category 字段。
SECRET_KEY（security 分类）不可通过 API 修改，仅脱敏可见。
"""
import os
import subprocess
import sys
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AdminUser, CurrentUser
from app.logger import logger
from models import SessionLocal
from models.system import SystemSetting

router = APIRouter()


def _get_setting(key: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return row.value if row else ''
    finally:
        db.close()


def _set_setting(key: str, value: str, category: str = 'runtime'):
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value, category=category))
        db.commit()
    finally:
        db.close()


def _find_embedding_path() -> Optional[str]:
    """查找 embedding 模型实际路径"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(project_root, 'models', 'embeddings')
    model_name = 'bge-m3'
    possible_paths = [
        os.path.join(cache_dir, model_name, 'BAAI', model_name),
        os.path.join(cache_dir, model_name),
        os.path.join(cache_dir, f'BAAI/{model_name}'.replace('/', os.sep)),
    ]
    for path in possible_paths:
        config_file = os.path.join(path, 'config.json')
        if os.path.exists(config_file):
            has_weights = any(
                os.path.exists(os.path.join(path, f))
                for f in ['pytorch_model.bin', 'model.safetensors', 'model.safetensors.index.json']
            )
            if has_weights:
                return path
    return None


def check_embedding_downloaded() -> bool:
    """检查模型是否已下载，并同步数据库状态"""
    found = _find_embedding_path() is not None
    if found:
        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_READY').first()
            if row is None or str(row.value) != 'true':
                if row:
                    row.value = 'true'
                else:
                    db.add(SystemSetting(key='EMBEDDING_MODEL_READY', value='true', category='runtime'))
                db.commit()
                logger.info("自动同步: EMBEDDING_MODEL_READY 更新为 true")
        except Exception as e:
            logger.warning(f"同步 EMBEDDING_MODEL_READY 失败: {e}")
        finally:
            db.close()
    return found


# ── Pydantic models ──────────────────────────────────────────────

class EmbeddingStatusResponse(BaseModel):
    downloaded: bool
    ready: bool
    model_path: str


class SystemSettingItem(BaseModel):
    key: str
    value: str
    category: Optional[str] = None


class UpdateSettingRequest(BaseModel):
    key: str
    value: str


class SiteBrandingResponse(BaseModel):
    logo: str
    site_name: str


# ── Embedding endpoints ──────────────────────────────────────────

@router.get("/embedding-status", response_model=EmbeddingStatusResponse)
def get_embedding_status(user: CurrentUser):
    """获取 embedding 模型下载状态"""
    found = _find_embedding_path()
    downloaded = found is not None
    if downloaded:
        _set_setting('EMBEDDING_MODEL_READY', 'true')
    db_ready = _get_setting('EMBEDDING_MODEL_READY') == 'true'
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    default_path = os.path.join(project_root, 'models', 'embeddings', 'bge-m3')
    return EmbeddingStatusResponse(
        downloaded=downloaded,
        ready=db_ready,
        model_path=found or default_path
    )


@router.post("/download-embedding")
def download_embedding(user: CurrentUser):
    """触发下载 embedding 模型（后台异步）"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        script_path = os.path.join(project_root, 'download_model.py')
        if os.name == 'nt':
            subprocess.Popen([sys.executable, script_path],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, script_path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("触发 embedding 模型下载")
        return {"success": True, "message": "下载已启动，请等待完成后刷新页面"}
    except Exception as e:
        logger.error(f"启动下载失败: {e}")
        return {"success": False, "message": f"启动下载失败: {str(e)}"}


# ── Settings endpoints ───────────────────────────────────────────

@router.get("/site-branding", response_model=SiteBrandingResponse)
def get_site_branding():
    """站点品牌配置（公开接口：登录页等未登录场景也需读取）"""
    return SiteBrandingResponse(
        logo=_get_setting('SITE_LOGO') or '/static/img/logo.svg',
        site_name=_get_setting('SITE_NAME') or 'QueryForge',
    )


@router.get("/settings", response_model=List[SystemSettingItem])
def get_settings(user: AdminUser):
    """获取所有系统配置（密钥类 value 脱敏；仅管理员）"""
    db = SessionLocal()
    try:
        rows = db.query(SystemSetting).all()
        result = []
        for r in rows:
            value = r.value or ''
            # security 分类（如 SECRET_KEY）脱敏显示
            if r.category == 'security' and value:
                value = value[:8] + '****' + value[-4:] if len(value) > 12 else '****'
            result.append(SystemSettingItem(key=r.key, value=value, category=r.category))
        return result
    finally:
        db.close()


@router.put("/settings")
def update_setting(req: UpdateSettingRequest, user: AdminUser):
    """更新系统配置（仅 auth/vector 分类可改；仅管理员）"""
    # 仅允许编辑标记为 is_editable 的配置项（排除 security / runtime）
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == req.key).first()
        if not row or not row.is_editable:
            raise HTTPException(status_code=400, detail=f"不可修改的配置项: {req.key}")
        row.value = req.value
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
    logger.info(f"系统配置已更新: {req.key}")
    return {"success": True, "message": f"{req.key} 已更新"}
