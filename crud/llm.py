# -*- coding: UTF-8 -*-
"""crud.llm — LLM 配置与调用遥测数据访问（主库 + 遥测库）

主库：LLMConfig / LLMUsageStat
遥测库：LLMCall / LLMPrompt（telemetry=True）
"""
from typing import List, Optional

from crud.base import BaseCrud, session_scope
from models.llm import LLMCall, LLMConfig, LLMPrompt, LLMUsageStat


class LLMConfigCrud(BaseCrud):
    model = LLMConfig

    def get_user_default(self, user_id: int) -> Optional[LLMConfig]:
        return self.get_one(user_id=user_id, is_default=True, is_active=True)

    def get_active_for_user(self, config_id: int, user_id: int) -> Optional[LLMConfig]:
        """取用户可用配置（公开配置 或 本人配置）"""
        from sqlalchemy import or_
        with session_scope() as db:
            obj = (db.query(LLMConfig)
                   .filter(LLMConfig.id == config_id,
                           LLMConfig.is_active == True,
                           or_(LLMConfig.is_public == True,
                               LLMConfig.user_id == user_id))
                   .first())
            # session_scope 退出会 commit（属性过期）+ close（脱离），
            # 必须 expunge 后再返回，否则会话外访问属性触发 DetachedInstanceError
            if obj is not None:
                db.expunge(obj)
            return obj

    def list_by_user(self, user_id: int) -> List[LLMConfig]:
        return self.list(user_id=user_id, order_by='created_at', desc=True)

    def list_visible(self, user_id: int, is_admin: bool = False) -> List[LLMConfig]:
        """管理员看全部；普通用户看自己的 + 公开的"""
        if is_admin:
            return self.list_all(order_by='created_at', desc=True)
        from sqlalchemy import or_
        with session_scope() as db:
            rows = (db.query(LLMConfig)
                    .filter(or_(LLMConfig.user_id == user_id,
                                LLMConfig.is_public == True))
                    .order_by(LLMConfig.created_at.desc()).all())
            # expunge 后再返回，避免会话外访问过期属性（同 get_active_for_user）
            for r in rows:
                db.expunge(r)
            return rows


class LLMUsageStatCrud(BaseCrud):
    model = LLMUsageStat


class LLMCallCrud(BaseCrud):
    model = LLMCall

    def list(self, order_by=None, desc=False, telemetry=True, **filters):
        # 遥测模型强制走遥测库
        return super().list(order_by=order_by, desc=desc, telemetry=True, **filters)

    def get_by_id(self, pk, telemetry=True):
        return super().get_by_id(pk, telemetry=True)

    def count(self, telemetry=True, **filters):
        return super().count(telemetry=True, **filters)

    def list_by_user(self, user_id: int, limit: int = 100) -> List[LLMCall]:
        return self.list(user_id=user_id, order_by='created_at', desc=True)[:limit]


class LLMPromptCrud(BaseCrud):
    model = LLMPrompt

    def list(self, order_by=None, desc=False, telemetry=True, **filters):
        return super().list(order_by=order_by, desc=desc, telemetry=True, **filters)

    def get_by_id(self, pk, telemetry=True):
        return super().get_by_id(pk, telemetry=True)

    def get_by_hash(self, content_hash: str) -> Optional[LLMPrompt]:
        return self.get_one(content_hash=content_hash, telemetry=True)


llm_config_crud = LLMConfigCrud()
llm_usage_stat_crud = LLMUsageStatCrud()
llm_call_crud = LLMCallCrud()
llm_prompt_crud = LLMPromptCrud()
