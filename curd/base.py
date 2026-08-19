# -*- coding: UTF-8 -*-
"""curd 数据访问层基础 — 统一会话管理 + 泛型 CRUD

设计目标（减少查询重复）：
1. session_scope()：上下文管理器，自动 commit/rollback/close，
   替代散落各处的 `db = SessionLocal(); try: ... finally: db.close()`。
2. BaseCrud 泛型：提供 get_by_id / get_one / list / count / exists /
   create / update / delete 等通用方法，各功能模块继承并补充业务查询。

用法：
    from curd.base import session_scope, BaseCrud
    with session_scope() as db:          # 单会话多步操作
        row = db.query(User).first()

    from curd.user import user_crud
    u = user_crud.get_by_id(1)            # 单步 CRUD，内部自管会话
"""
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Type, TypeVar

from db import SessionLocal, TelemetrySessionLocal

T = TypeVar('T')


@contextmanager
def session_scope(telemetry: bool = False):
    """数据库会话上下文管理器 — 自动 commit / rollback / close。

    用法：
        with session_scope() as db:
            db.add(obj)
            db.query(User).filter(...)
    块内抛异常自动 rollback，正常结束自动 commit。
    """
    session = TelemetrySessionLocal() if telemetry else SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def tx_scope(telemetry: bool = False):
    """显式事务会话 — 不自动 commit，由调用方在块内手动 db.commit()。

    适用于需要多次 commit（分步落库）或先读后写的场景。
    """
    session = TelemetrySessionLocal() if telemetry else SessionLocal()
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
    """
    model: Type[Any] = None          # 子类必须指定

    # ── 查询 ──────────────────────────────────────────────────

    def get_by_id(self, pk: int, telemetry: bool = False) -> Optional[Any]:
        with session_scope(telemetry=telemetry) as db:
            obj = db.query(self.model).filter(self.model.id == pk).first()
            if obj is not None:
                db.expunge(obj)
            return obj

    def get_one(self, telemetry: bool = False, **filters) -> Optional[Any]:
        """按字段等值条件取单条（如 get_one(username='admin', is_active=1)）"""
        with session_scope(telemetry=telemetry) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            obj = q.first()
            if obj is not None:
                db.expunge(obj)
            return obj

    def list(self, order_by: Optional[str] = None, desc: bool = False,
             telemetry: bool = False, **filters) -> List[Any]:
        """按字段等值条件列表；order_by 为模型字段名（如 'created_at'）"""
        with session_scope(telemetry=telemetry) as db:
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
                 telemetry: bool = False) -> List[Any]:
        return self.list(order_by=order_by, desc=desc, telemetry=telemetry)

    def count(self, telemetry: bool = False, **filters) -> int:
        with session_scope(telemetry=telemetry) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.count()

    def exists(self, telemetry: bool = False, **filters) -> bool:
        return self.count(telemetry=telemetry, **filters) > 0

    # ── 写入 ──────────────────────────────────────────────────

    def create(self, commit: bool = True, telemetry: bool = False, **data) -> Any:
        """创建并返回对象；commit=False 时不提交（配合 tx_scope 使用）"""
        with session_scope(telemetry=telemetry) as db:
            obj = self.model(**data)
            db.add(obj)
            db.flush()
            db.refresh(obj)
            db.expunge(obj)
            return obj

    def update(self, pk: int, commit: bool = True, telemetry: bool = False,
               **data) -> Optional[Any]:
        """按主键更新指定字段，返回更新后的对象；不存在返回 None"""
        with session_scope(telemetry=telemetry) as db:
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
                  **kwargs) -> int:
        """按等值条件批量更新；kwargs 中 filter_ 前缀键为过滤条件，其余为更新值。

        用法：update_by(filter_user_id=1, is_active=0)
        """
        filters = {k[7:]: v for k, v in kwargs.items() if k.startswith('filter_')}
        updates = {k: v for k, v in kwargs.items() if not k.startswith('filter_')}
        with session_scope(telemetry=telemetry) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.update(updates, synchronize_session=False)

    def delete(self, pk: int, telemetry: bool = False) -> bool:
        """按主键删除，返回是否删除成功"""
        with session_scope(telemetry=telemetry) as db:
            obj = db.query(self.model).filter(self.model.id == pk).first()
            if not obj:
                return False
            db.delete(obj)
            return True

    def delete_by(self, telemetry: bool = False, **filters) -> int:
        """按等值条件批量删除，返回删除行数"""
        with session_scope(telemetry=telemetry) as db:
            q = db.query(self.model)
            for key, value in filters.items():
                q = q.filter(getattr(self.model, key) == value)
            return q.delete(synchronize_session=False)
