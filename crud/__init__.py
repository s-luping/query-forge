# -*- coding: UTF-8 -*-
"""crud 数据访问层 — 按功能分模块的数据库操作封装

统一会话管理（crud.base.session_scope）消除散落的
`db = SessionLocal(); try: ... finally: db.close()` 样板；
各功能模块提供覆盖常用查询/写入的 CRUD 方法，减少重复查询。

用法：
    from crud.base import session_scope, tx_scope
    from crud.user import user_crud
    from crud.role import role_crud, role_permission_crud
    from crud.schema import schema_crud, table_crud, column_crud
    from crud.knowledge import knowledge_crud
    from crud.conversation import conversation_crud, message_crud
    from crud.llm import llm_config_crud, llm_call_crud
    from crud.system import system_setting_crud
    from crud.datasource import datasource_crud
    from crud.sync import sync_job_crud, sync_run_crud, change_crud
    from crud.security import audit_crud
    from crud.vector import vector_index_crud
"""
from crud.base import BaseCrud, session_scope, tx_scope

__all__ = ['BaseCrud', 'session_scope', 'tx_scope']
