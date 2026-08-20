# -*- coding: UTF-8 -*-
"""crud.security — 安全审计数据访问

用法：
    from crud.security import audit_crud
    audit_crud.create(user_id=1, username='admin', query='...')
"""
from crud.base import BaseCrud
from models.security import QueryAuditLog


class AuditCrud(BaseCrud):
    model = QueryAuditLog

    def list_by_user(self, user_id: int, limit: int = 100) -> list:
        return self.list(user_id=user_id, order_by='created_at', desc=True)[:limit]

    def delete_by_user(self, user_id: int) -> int:
        return self.delete_by(user_id=user_id)


audit_crud = AuditCrud()
