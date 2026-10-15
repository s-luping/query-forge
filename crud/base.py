# -*- coding: UTF-8 -*-
"""crud 数据访问层基础 — 统一会话管理 + 泛型 CRUD

设计目标（减少查询重复）：
1. session_scope()：上下文管理器，自动 commit/rollback/close，
   替代散落各处的 `db = SessionLocal(); try: ... finally: db.close()`。
2. BaseCrud 泛型：提供 get_by_id / get_one / list / count / exists /
   create / update / delete 等通用方法，各功能模块继承并补充业务查询。

用法：
    from crud.base import session_scope, BaseCrud
    with session_scope() as db:          # 单会话多步操作
        row = db.query(User).filter(...)

    from crud.user import user_crud
    u = user_crud.get_by_id(1)            # 单步 CRUD，内部自管会话

会话语义（expire_on_commit=False，见 db/engine.py）：
    - commit 不再过期属性，实例脱离会话（close 后）仍可安全读属性；
      逃出 with 块的 ORM 对象无需强制 expunge（expunge 仍是推荐写法，
      语义为"显式声明快照离开"）
    - 例外：同会话内用 query.update/delete(synchronize_session=False) bulk
      改过的行，其已加载的 ORM 实例不会同步——之后再读这些行必须重新 query，
      或改用 synchronize_session='fetch'

库选择（三库分离）：
    session_scope()                → 主库（默认）
    session_scope(telemetry=True)  → 遥测库
    session_scope(logs=True)       → 日志库
    BaseCrud 子类声明 default_db='logs'/'telemetry' 后，通用方法自动走对应库。
"""
from contextlib import contextmanager
from typing import Any, List, Optional, Type, TypeVar

from db import LogsSessionLocal, SessionLocal, TelemetrySessionLocal

T = TypeVar('T')


@contextmanager
def session_scope(telemetry: bool = False, logs: bool = False):
    """数据库会话上下文管理器 — 自动 commit / rollback / close。

    用法：
        with session_scope() as db:
            db.add(obj)
            db.query(User).filter(...)
        with session_scope(logs=True) as db:   # 日志库
            db.query(QueryAuditLog)...
    块内抛异常自动 rollback，正常结束自动 commit。
    """
    if telemetry and logs:
        raise ValueError('telemetry 与 logs 互斥，一个会话只能绑定一个库')
    session = (TelemetrySessionLocal() if telemetry
               else LogsSessionLocal() if logs
               else SessionLocal())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def tx_scope(telemetry: bool = False, logs: bool = False):
    """显式事务会话 — 不自动 commit，由调用方在块内手动 db.commit()。

    适用于需要多次 commit（分步落库）或先读后写的场景。
    """
    if telemetry and logs:
        raise ValueError('telemetry 与 logs 互斥，一个会话只能绑定一个库')
    session = (TelemetrySessionLocal() if telemetry
               else LogsSessionLocal() if logs
               else SessionLocal())
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class BaseCrud:
    """泛型 CRUD — 子类声明 model = <ORM 模型> 即可获得通用方法。

    每个方法内部自管会话（自动 open/commit/close），调用方无需接触 Session。
    如需多步事务，用 session_scope()/tx_scope() 获取会话后自行操作。

    库绑定：子类声明 default_db = 'main' | 'telemetry' | 'logs'，
    通用方法默认走该库；调用时也可用 telemetry=True / logs=True 临时覆盖。
    """
    model: Type[Any] = None          # 子类必须指定
    default_db: str = 'main'         # 子类可覆盖：'telemetry' / 'logs'

    def _use_logs(self, telemetry: bool, logs: bool) -> bool:
        """按 default_db + 显式参数解析本次走不走日志库"""
        if telemetry and logs:
            raise ValueError('telemetry 与 logs 互斥，一个会话只能绑定一个库')
        if logs:
            return True
        if telemetry:
            return False
        return self.default_db == 'logs'

    # ── 查询 ──────────────────────────────────────────────────

    def get_by_id(self, pk: int, telemetry: bool = False,
                  logs: bool = False) -> Optional[Any]:
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            obj = db.query(self.model).filter(self.model.id == pk).first()
            if obj is not None:
                db.expunge(obj)
            return obj

    def get_one(self, telemetry: bool = False, logs: bool = False,
                **filters) -> Optional[Any]:
        """按字段等值条件取单条（如 get_one(username='admin', is_active=1)）"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            obj = q.first()
            if obj is not None:
                db.expunge(obj)
            return obj

    def list(self, order_by: Optional[str] = None, desc: bool = False,
             telemetry: bool = False, logs: bool = False,
             **filters) -> List[Any]:
        """按字段等值条件列表；order_by 为模型字段名（如 'created_at'）"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            if order_by:
                col = getattr(self.model, order_by)
                q = q.order_by(col.desc() if desc else col.asc())
            rows = q.all()
            for obj in rows:
                db.expunge(obj)
            return rows

    def list_all(self, order_by: Optional[str] = None, desc: bool = False,
                 telemetry: bool = False, logs: bool = False) -> List[Any]:
        return self.list(order_by=order_by, desc=desc,
                         telemetry=telemetry, logs=logs)

    def count(self, telemetry: bool = False, logs: bool = False,
              **filters) -> int:
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.count()

    def exists(self, telemetry: bool = False, logs: bool = False,
               **filters) -> bool:
        return self.count(telemetry=telemetry, logs=logs, **filters) > 0

    # ── 写入 ──────────────────────────────────────────────────

    def create(self, commit: bool = True, telemetry: bool = False,
               logs: bool = False, **data) -> Any:
        """创建并返回对象；commit=False 时不提交（配合 tx_scope 使用）"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            obj = self.model(**data)
            db.add(obj)
            db.flush()
            db.refresh(obj)
            db.expunge(obj)
            return obj

    def update(self, pk: int, commit: bool = True, telemetry: bool = False,
               logs: bool = False, **data) -> Optional[Any]:
        """按主键更新指定字段，返回更新后的对象；不存在返回 None"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            obj = db.query(self.model).filter(self.model.id == pk).first()
            if not obj:
                return None
            for key, value in data.items():
                setattr(obj, key, value)
            db.flush()
            db.refresh(obj)
            db.expunge(obj)
            return obj

    def update_by(self, commit: bool = True, telemetry: bool = False,
                  logs: bool = False, **kwargs) -> int:
        """按等值条件批量更新；kwargs 中 filter_ 前缀键为过滤条件，其余为更新值。

        用法：update_by(filter_user_id=1, is_active=0)
        """
        filters = {k[7:]: v for k, v in kwargs.items() if k.startswith('filter_')}
        updates = {k: v for k, v in kwargs.items() if not k.startswith('filter_')}
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.update(updates, synchronize_session=False)

    def delete(self, pk: int, telemetry: bool = False,
               logs: bool = False) -> bool:
        """按主键删除，返回是否删除成功"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            obj = db.query(self.model).filter(self.model.id == pk).first()
            if not obj:
                return False
            db.delete(obj)
            return True

    def delete_by(self, telemetry: bool = False, logs: bool = False,
                  **filters) -> int:
        """按等值条件批量删除，返回删除行数"""
        with session_scope(telemetry=telemetry,
                           logs=self._use_logs(telemetry, logs)) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.delete(synchronize_session=False)
