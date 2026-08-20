# -*- coding: UTF-8 -*-
"""crud.user — 用户数据访问

用法：
    from crud.user import user_crud
    u = user_crud.get_by_id(1)
    u = user_crud.get_by_username('admin')
    users = user_crud.list(is_active=1)
"""
from typing import Optional

from crud.base import BaseCrud, session_scope
from models.user import User


class UserCrud(BaseCrud):
    model = User

    # ── 业务查询 ──────────────────────────────────────────────

    def get_by_username(self, username: str) -> Optional[User]:
        return self.get_one(username=username)

    def get_by_email(self, email: str) -> Optional[User]:
        if not email:
            return None
        return self.get_one(email=email)

    def count_admins(self) -> int:
        return self.count(role='admin')

    def list_active(self) -> list:
        return self.list(is_active=1, order_by='id')

    def update_last_login(self, user_id: int) -> None:
        from app.timezone import now_beijing
        self.update(user_id, last_login=now_beijing())

    def refresh_pwd_ts(self, user_id: int) -> None:
        """修改密码后刷新 pwd_ts，使该用户所有旧 token 失效"""
        import time
        self.update(user_id, pwd_ts=time.time())


user_crud = UserCrud()
