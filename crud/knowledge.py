# -*- coding: UTF-8 -*-
"""crud.knowledge — 知识库数据访问

用法：
    from crud.knowledge import knowledge_crud
    items = knowledge_crud.list_active(user_id=1)
"""
from typing import Optional

from crud.base import BaseCrud, session_scope
from models.knowledge import KnowledgeItem


class KnowledgeCrud(BaseCrud):
    model = KnowledgeItem

    def get_active(self, item_id: int) -> Optional[KnowledgeItem]:
        return self.get_one(id=item_id, is_active=1)

    def list_by_user(self, user_id: int) -> list:
        return self.list(user_id=user_id, order_by='created_at', desc=True)

    def list_active(self, user_id: Optional[int] = None) -> list:
        if user_id is not None:
            return self.list(user_id=user_id, is_active=1,
                             order_by='created_at', desc=True)
        return self.list(is_active=1, order_by='created_at', desc=True)

    def list_all_visible(self, user_id: int) -> list:
        """管理员看全部启用条目；普通用户看自己创建的启用条目"""
        return self.list_active(user_id=user_id)


knowledge_crud = KnowledgeCrud()
