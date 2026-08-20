# -*- coding: UTF-8 -*-
"""定时元数据同步 — 每 10 分钟检查所有启用的同步任务

调度策略：
    - interval 类型：schedule_value 为分钟数，检查距 last_synced_at 是否已过间隔
    - cron 类型：暂不支持自动调度（可通过手动触发）
    - manual 类型：仅手动触发

同步在后台线程执行，不阻塞调度器事件循环。
"""
from datetime import datetime, timedelta
from app.logger import logger
from app.timezone import now_beijing


def run_scheduled_syncs():
    """检查并执行所有到期的同步任务"""
    from crud.base import session_scope
    from models.sync import SyncJobConfig
    from models.datasource import DataSource
    from services.sync_engine import SyncEngine

    try:
        with session_scope() as db:
            jobs = db.query(SyncJobConfig).filter(
                SyncJobConfig.is_enabled == True,
                SyncJobConfig.schedule_type == 'interval',
            ).all()

            if not jobs:
                return

            now = now_beijing()
            due_jobs = []

            for job in jobs:
                try:
                    interval_minutes = int(job.schedule_value)
                except (ValueError, TypeError):
                    logger.warning(f"同步任务 {job.id} schedule_value 无效: {job.schedule_value}")
                    continue

                # 新建任务不立即执行：按创建时间计算首个周期，避免调度器启动后
                # 第一次十分钟巡检绕过用户配置的 interval。
                reference_time = job.last_synced_at or job.created_at
                if reference_time and now - reference_time >= timedelta(minutes=interval_minutes):
                    due_jobs.append(job)

            if not due_jobs:
                return

            logger.info(f"定时同步: {len(due_jobs)}/{len(jobs)} 个任务到期")

            for job in due_jobs:
                ds = db.query(DataSource).filter(
                    DataSource.id == job.datasource_id).first()
                if not ds:
                    logger.warning(f"同步任务 {job.id} 数据源不存在，跳过")
                    continue

                # 标记为 running 防止重复执行
                job.last_sync_status = 'running'

                try:
                    engine = SyncEngine(job, ds, triggered_by='scheduler')
                    engine.run()
                except Exception as e:
                    logger.error(f"同步任务 {job.id} 执行失败: {e}", exc_info=True)
                    job.last_sync_status = 'failed'
    except Exception as e:
        logger.error(f"定时同步检查失败: {e}", exc_info=True)
