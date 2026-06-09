"""系统配置路由 — 系统参数、embedding状态"""
import os
import subprocess
import sys
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.logger import logger
from models import AppSessionLocal
from models.system import SystemConfig

router = APIRouter()


def _get_setting(key: str) -> str:
    db = AppSessionLocal()
    try:
        row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        return row.value if row else ''
    finally:
        db.close()


def _set_setting(key: str, value: str):
    db = AppSessionLocal()
    try:
        row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if row:
            row.value = value
        else:
            db.add(SystemConfig(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _find_embedding_path() -> Optional[str]:
    """查找 embedding 模型实际路径（匹配 VectorStore 的多路径查找）"""
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
    return _find_embedding_path() is not None


# ── Pydantic models ──────────────────────────────────────────────

class EmbeddingStatusResponse(BaseModel):
    downloaded: bool
    model_path: str


class SystemSettingItem(BaseModel):
    key: str
    value: str


class UpdateSettingRequest(BaseModel):
    key: str
    value: str


# ── Embedding endpoints ──────────────────────────────────────────

@router.get("/embedding-status", response_model=EmbeddingStatusResponse)
def get_embedding_status(user=Depends(get_current_user)):
    """获取 embedding 模型下载状态"""
    found = _find_embedding_path()
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    default_path = os.path.join(project_root, 'models', 'embeddings', 'bge-m3')
    return EmbeddingStatusResponse(
        downloaded=found is not None,
        model_path=found or default_path
    )


@router.post("/download-embedding")
def download_embedding(user=Depends(get_current_user)):
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

@router.get("/settings", response_model=List[SystemSettingItem])
def get_settings(user=Depends(get_current_user)):
    """获取所有系统配置"""
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可查看")
    db = AppSessionLocal()
    try:
        rows = db.query(SystemConfig).filter(SystemConfig.key != 'SECRET_KEY').all()
        return [SystemSettingItem(key=r.key, value=r.value or '') for r in rows]
    finally:
        db.close()


@router.put("/settings")
def update_setting(req: UpdateSettingRequest, user=Depends(get_current_user)):
    """更新系统配置"""
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可修改")
    allowed_keys = {'ACCESS_TOKEN_EXPIRE_MINUTES'}
    if req.key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"不可修改的配置项: {req.key}")
    _set_setting(req.key, req.value)
    logger.info(f"系统配置已更新: {req.key}")
    return {"success": True, "message": f"{req.key} 已更新"}
