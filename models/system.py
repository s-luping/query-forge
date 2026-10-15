"""系统配置模型 — 键值对存储（带语义分类）

category 分类：
- security     密钥类（SECRET_KEY），仅管理员脱敏可见，不可通过 API 修改
- auth         认证参数（ACCESS_TOKEN_EXPIRE_MINUTES）
- runtime      运行时状态缓存（EMBEDDING_MODEL_READY / EMBEDDING_MODEL_PATH），系统自动维护
- vector       向量检索业务参数（VECTOR_INDEX_THRESHOLD / FIELD_RECALL_TOP_K / MAX_TABLES）
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.timezone import now_beijing
from models.base import MainBase


class SystemSetting(MainBase):
    """系统配置表"""
    __tablename__ = 'system_settings'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    key = Column(String(100), unique=True, nullable=False, index=True, comment='配置键')
    value = Column(Text, comment='配置值')
    category = Column(String(30), default='general', comment='分类: security|auth|runtime|vector|general')
    is_editable = Column(Integer, default=1, comment='是否可通过设置页修改(1/0)')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


# 兼容别名：旧脚本（download_model.py / scripts/demo.py 等）仍引用 SystemConfig
SystemConfig = SystemSetting
