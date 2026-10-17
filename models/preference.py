# -*- coding: UTF-8 -*-
"""用户偏好模型 — 表名 user_preferences（key-value，JSON 值）

用途：用户级持久化偏好，如默认勾选的知识库条目（default_knowledge_ids）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.timezone import now_beijing
from models.base import MainBase


class UserPreference(MainBase):
    """用户偏好表"""
    __tablename__ = 'user_preferences'
    user_id = Column(Integer, primary_key=True, comment='用户ID（联合主键）')
    pref_key = Column(String(50), primary_key=True, comment='偏好键（联合主键）')
    pref_value = Column(Text, comment='偏好值（JSON）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing,
                        comment='更新时间（北京时间）')
