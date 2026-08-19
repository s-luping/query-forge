# -*- coding: UTF-8 -*-
"""curd.system — 系统设置数据访问

用法：
    from curd.system import system_setting_crud
    v = system_setting_crud.get_value('SECRET_KEY')
    system_setting_crud.set_value('SITE_NAME', 'My Site')
"""
from typing import Optional

from curd.base import BaseCrud, session_scope
from models.system import SystemSetting


class SystemSettingCrud(BaseCrud):
    model = SystemSetting

    def get_value(self, key: str) -> str:
        """读取配置值；不存在返回空串"""
        row = self.get_one(key=key)
        return str(row.value) if row is not None and row.value is not None else ''

    def set_value(self, key: str, value: str, category: str = 'runtime',
                  is_editable: Optional[int] = None) -> None:
        """写入配置值（存在则更新，否则新增）"""
        with session_scope() as db:
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row:
                row.value = value
            else:
                db.add(SystemSetting(key=key, value=value, category=category,
                                     is_editable=is_editable))

    def list_all_settings(self) -> list:
        return self.list_all(order_by='key')

    def delete_by_key(self, key: str) -> int:
        return self.delete_by(key=key)


system_setting_crud = SystemSettingCrud()
