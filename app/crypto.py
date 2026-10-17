# -*- coding: UTF-8 -*-
"""安全模块 — api_key 加解密（Fernet 对称加密）

密钥从系统设置中的 SECRET_KEY 派生（SHA-256 → urlsafe base64），
无需额外的密钥管理。密文带 "enc::" 前缀，兼容读取历史明文。
"""
import base64
import hashlib

_PREFIX = 'enc::'

_fernet_instance = None


def _get_fernet():
    global _fernet_instance
    if _fernet_instance is None:
        from cryptography.fernet import Fernet

        from app.config import FERNET_KEY
        if FERNET_KEY:
            # 独立 Fernet 密钥（推荐），与 JWT 签名密钥分离
            _fernet_instance = Fernet(FERNET_KEY.encode('utf-8'))
        else:
            # 兼容旧部署：从 SECRET_KEY 派生
            from app.auth import _get_secret_key
            digest = hashlib.sha256(_get_secret_key().encode('utf-8')).digest()
            _fernet_instance = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet_instance


def encrypt_secret(plain: str) -> str:
    """加密明文。加密失败直接抛错拒绝保存——绝不静默回退明文落库
    （API Key / 数据源密码明文进 DB 属敏感信息泄漏，宁可让保存操作失败）。"""
    if not plain:
        return plain
    return _PREFIX + _get_fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt_secret(stored: str) -> str:
    """解密密文。无前缀的历史明文原样返回。"""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    try:
        return _get_fernet().decrypt(stored[len(_PREFIX):].encode('utf-8')).decode('utf-8')
    except Exception:
        # SECRET_KEY 轮换后旧密文无法解密，返回占位符迫使管理员重填
        return ''


def mask_api_key(api_key: str) -> str:
    """脱敏展示"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]
