# -*- coding: UTF-8 -*-
"""crud.datasource — 数据源数据访问

用法：
    from crud.datasource import datasource_crud
    ds = datasource_crud.get_by_id(1)
    exists = datasource_crud.exists(name='my-db')
"""
from typing import Optional

from crud.base import BaseCrud, session_scope
from models.datasource import DataSource
from models.schema import DbSchema
from models.sync import SchemaChangeLog, SyncJobConfig, SyncRunLog


class DataSourceCrud(BaseCrud):
    model = DataSource

    def get_by_name(self, name: str) -> Optional[DataSource]:
        return self.get_one(name=name)

    def name_exists(self, name: str, exclude_id: Optional[int] = None) -> bool:
        """名称是否被占用（编辑时排除自身）"""
        with session_scope() as db:
            q = db.query(DataSource).filter(DataSource.name == name)
            if exclude_id:
                q = q.filter(DataSource.id != exclude_id)
            return q.first() is not None

    def list_all_sorted(self) -> list:
        return self.list_all(order_by='created_at', desc=True)

    def count_active(self) -> int:
        return self.count(status='active')

    def mark_tested(self, ds_id: int, ok: bool, message: str) -> None:
        """测试连接后更新状态与错误信息"""
        from app.timezone import now_beijing
        self.update(ds_id,
                    last_tested_at=now_beijing(),
                    status='active' if ok else 'error',
                    last_error='' if ok else message[:500])

    def delete_cascade(self, ds_id: int) -> int:
        """级联删除数据源：变更记录 → 执行历史 → 同步任务 → 解除库绑定 → 数据源。

        跨库拆分：前两步（日志表）在日志库执行，后续在主库执行。
        主库原开外键约束按依赖顺序清理；日志库无外键，顺序无关但保持先日志后主库，
        避免中途失败时主库配置已删而日志残留引用失效的 id。
        返回清理的同步任务数。
        """
        with session_scope() as db:
            ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
            if not ds:
                return -1
            job_ids = [j[0] for j in db.query(SyncJobConfig.id).filter(
                SyncJobConfig.datasource_id == ds_id).all()]
        # 1) 日志库：变更记录（引用 datasource_id / job_id）→ 执行历史（引用 job_id）
        with session_scope(logs=True) as ldb:
            ldb.query(SchemaChangeLog).filter(
                SchemaChangeLog.datasource_id == ds_id).delete()
            if job_ids:
                ldb.query(SyncRunLog).filter(SyncRunLog.job_id.in_(job_ids)).delete()
        # 2) 主库：同步任务 → 解除库绑定 → 数据源
        with session_scope() as db:
            db.query(SyncJobConfig).filter(
                SyncJobConfig.datasource_id == ds_id).delete()
            # 该数据源同步出的库解除绑定（保留结构元数据，不误删）
            db.query(DbSchema).filter(DbSchema.datasource_id == ds_id).update(
                {DbSchema.datasource_id: None})
            db.delete(ds)
            return len(job_ids)


datasource_crud = DataSourceCrud()
