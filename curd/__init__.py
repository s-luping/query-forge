# -*- coding: UTF-8 -*-
"""curd 数据访问层 — 按功能分模块的数据库操作封装

统一会话管理（curd.base.session_scope）消除散落的
`db = SessionLocal(); try: ... finally: db.close()` 样板；
各功能模块提供覆盖常用查询/写入的 CRUD 方法，减少重复查询。

用法：
    from curd.base import session_scope, tx_scope
    from curd.user import user_crud
    from curd.role import role_crud, role_permission_crud
    from curd.schema import schema_crud, table_crud, column_crud
    from curd.knowledge import knowledge_crud
    from curd.conversation import conversation_crud, message_crud
    from curd.llm import llm_config_crud, llm_call_crud
    from curd.system import system_setting_crud
    from curd.datasource import datasource_crud
    from curd.sync import sync_job_crud, sync_run_crud, change_crud
    from curd.security import audit_crud
    from curd.vector import vector_index_crud
"""
from curd.base import BaseCrud, session_scope, tx_scope

__all__ = ['BaseCrud', 'session_scope', 'tx_scope']
