# -*- coding: UTF-8 -*-
"""crud.sync — 同步任务 / 执行历史 / 变更记录数据访问

用法：
    from crud.sync import sync_job_crud, sync_run_crud, change_crud
    job = sync_job_crud.get_by_id(1)

多表联查（join 数据源、批量取 schema 名、统计聚合）集中在本模块，
router 只负责参数校验与响应组装。
"""
from typing import Dict, List, Optional, Tuple

from crud.base import BaseCrud, session_scope
from models.datasource import DataSource
from models.sync import SchemaChangeLog, SyncJobConfig, SyncRunLog


class SyncJobCrud(BaseCrud):
    model = SyncJobConfig

    def get_by_datasource_and_schema(self, datasource_id: int,
                                     schema_name: str) -> Optional[SyncJobConfig]:
        return self.get_one(datasource_id=datasource_id,
                            target_schema_name=schema_name)

    def list_enabled(self) -> List[SyncJobConfig]:
        return self.list(is_enabled=True)

    def list_ids_by_datasource(self, datasource_id: int) -> List[int]:
        with session_scope() as db:
            return [r[0] for r in db.query(SyncJobConfig.id).filter(
                SyncJobConfig.datasource_id == datasource_id).all()]

    def list_with_datasource(self) -> List[Tuple[SyncJobConfig, str, str]]:
        """任务 + 数据源名称 + 数据库名（join，一次查询）"""
        with session_scope() as db:
            rows = (db.query(SyncJobConfig, DataSource.name, DataSource.database)
                    .join(DataSource, SyncJobConfig.datasource_id == DataSource.id)
                    .order_by(SyncJobConfig.created_at.desc()).all())
            result = []
            for job, ds_name, ds_db in rows:
                db.expunge(job)
                result.append((job, ds_name, ds_db))
            return result

    def schema_name_by_id(self, job_id: int) -> str:
        """任务的 target_schema_name（供 run 详情展示）"""
        with session_scope() as db:
            row = db.query(SyncJobConfig.target_schema_name).filter(
                SyncJobConfig.id == job_id).first()
            return row[0] if row else ''

    def delete_cascade(self, job_id: int) -> None:
        """删除同步任务（连同执行历史与变更记录）

        跨库拆分：任务配置在主库，执行历史/变更记录在日志库，
        分两个会话清理（无分布式事务，先日志后主库）。
        """
        with session_scope(logs=True) as ldb:
            ldb.query(SchemaChangeLog).filter(SchemaChangeLog.job_id == job_id).delete()
            ldb.query(SyncRunLog).filter(SyncRunLog.job_id == job_id).delete()
        with session_scope() as db:
            db.query(SyncJobConfig).filter(SyncJobConfig.id == job_id).delete()


class SyncRunCrud(BaseCrud):
    model = SyncRunLog
    default_db = 'logs'   # 执行历史已拆至日志库（logs.db）

    def list_by_job(self, job_id: int, limit: int = 100) -> List[SyncRunLog]:
        return self.list(job_id=job_id, order_by='started_at', desc=True)[:limit]

    def count_failed(self) -> int:
        return self.count(status='failed')

    def count_success(self) -> int:
        return self.count(status='success')

    def list_paged(self, job_id: Optional[int], limit: int,
                   offset: int, status: Optional[str] = None) -> Tuple[List[SyncRunLog], int]:
        """分页列表 + 总数；批量取 job schema 名映射避免 N+1"""
        with session_scope(logs=True) as db:
            q = db.query(SyncRunLog)
            if job_id:
                q = q.filter(SyncRunLog.job_id == job_id)
            if status:
                q = q.filter(SyncRunLog.status == status)
            total = q.count()
            rows = q.order_by(SyncRunLog.started_at.desc()).limit(limit).offset(offset).all()
            for r in rows:
                db.expunge(r)
            return rows, total

    def schema_map_for_runs(self, run_ids: List[int]) -> Dict[int, str]:
        """批量取 run 对应的任务目标库名 {job_id: schema_name}（任务配置在主库）"""
        if not run_ids:
            return {}
        with session_scope() as db:
            return dict(db.query(SyncJobConfig.id, SyncJobConfig.target_schema_name)
                        .filter(SyncJobConfig.id.in_(run_ids)).all())


class ChangeCrud(BaseCrud):
    model = SchemaChangeLog
    default_db = 'logs'   # 变更记录已拆至日志库（logs.db）

    def list_by_job(self, job_id: int) -> List[SchemaChangeLog]:
        return self.list(job_id=job_id, order_by='created_at', desc=True)

    def count_pending(self) -> int:
        return self.count(approval_status='pending')

    def list_by_run(self, run_log_id: int) -> List[SchemaChangeLog]:
        return self.list(run_log_id=run_log_id, order_by='id')

    def list_paged(self, job_id: Optional[int], approval_status: Optional[str],
                   change_type: Optional[str], limit: int,
                   offset: int) -> Tuple[List[SchemaChangeLog], int]:
        with session_scope(logs=True) as db:
            q = db.query(SchemaChangeLog)
            if job_id:
                q = q.filter(SchemaChangeLog.job_id == job_id)
            if approval_status:
                q = q.filter(SchemaChangeLog.approval_status == approval_status)
            if change_type:
                q = q.filter(SchemaChangeLog.change_type == change_type)
            total = q.count()
            rows = q.order_by(SchemaChangeLog.created_at.desc()).limit(limit).offset(offset).all()
            for r in rows:
                db.expunge(r)
            return rows, total

    def get_pending(self, change_id: int) -> Optional[SchemaChangeLog]:
        """取待审批变更（非 pending 状态返回 None，供审批校验）"""
        return self.get_one(id=change_id, approval_status='pending')

    def pending_count_by_runs(self, run_log_ids: List[int]) -> Dict[int, int]:
        """批量统计各次运行当前仍处 pending 的变更数 {run_log_id: count}。

        用于「同步执行历史」的「待审批」列实时展示：审批/拒绝后该数应动态减少，
        而非读取运行记录里定格的 changes_pending 快照。
        """
        if not run_log_ids:
            return {}
        from sqlalchemy import func
        with session_scope(logs=True) as db:
            rows = (db.query(SchemaChangeLog.run_log_id,
                             func.count(SchemaChangeLog.id))
                    .filter(SchemaChangeLog.run_log_id.in_(run_log_ids),
                            SchemaChangeLog.approval_status == 'pending')
                    .group_by(SchemaChangeLog.run_log_id).all())
            return {rid: cnt for rid, cnt in rows}

    def pending_count_by_run(self, run_log_id: int) -> int:
        """单次运行当前仍处 pending 的变更数（详情接口用）"""
        return self.pending_count_by_runs([run_log_id]).get(run_log_id, 0)

    def clear_history(self) -> Tuple[int, int]:
        """清空全部执行历史与变更记录，返回 (runs, changes)"""
        with session_scope(logs=True) as db:
            changes = db.query(SchemaChangeLog).delete()
            runs = db.query(SyncRunLog).delete()
            return runs, changes


def get_sync_stats() -> dict:
    """同步统计概览（跨库：数据源/任务在主库，执行历史/变更在日志库）"""
    from sqlalchemy import func
    with session_scope() as db:
        total_ds = db.query(func.count(DataSource.id)).scalar() or 0
        active_ds = db.query(func.count(DataSource.id)).filter(
            DataSource.status == 'active').scalar() or 0
        total_jobs = db.query(func.count(SyncJobConfig.id)).scalar() or 0
        enabled_jobs = db.query(func.count(SyncJobConfig.id)).filter(
            SyncJobConfig.is_enabled == True).scalar() or 0
    with session_scope(logs=True) as db:
        total_runs = db.query(func.count(SyncRunLog.id)).scalar() or 0
        success_runs = db.query(func.count(SyncRunLog.id)).filter(
            SyncRunLog.status == 'success').scalar() or 0
        failed_runs = db.query(func.count(SyncRunLog.id)).filter(
            SyncRunLog.status == 'failed').scalar() or 0
        pending_changes = db.query(func.count(SchemaChangeLog.id)).filter(
            SchemaChangeLog.approval_status == 'pending').scalar() or 0
    return {
        "datasources": {"total": total_ds, "active": active_ds},
        "jobs": {"total": total_jobs, "enabled": enabled_jobs},
        "runs": {"total": total_runs, "success": success_runs, "failed": failed_runs},
        "changes": {"pending": pending_changes},
    }


sync_job_crud = SyncJobCrud()
sync_run_crud = SyncRunCrud()
change_crud = ChangeCrud()
