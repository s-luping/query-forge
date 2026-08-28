# -*- coding: UTF-8 -*-
"""调度器管理 — 注册定时聚合、清理与同步任务

任务清单：
  - aggregate_usage  每小时聚合 LLM 用量到 llm_usage_stats（回溯 7 天幂等覆盖）
  - cleanup_telemetry 每天凌晨 3 点清理过期遥测数据（默认保留 90 天）
  - run_scheduled_syncs 每 10 分钟检查并执行到期的元数据同步任务
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.logger import logger
from app.timezone import BEIJING_TZ
from scheduler.jobs.usage_stats import aggregate_usage_stats
from scheduler.jobs.retention import cleanup_telemetry, cleanup_main_db, wal_checkpoint
from scheduler.jobs.schema_sync import run_scheduled_syncs


class SchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=BEIJING_TZ)

    def init_scheduler(self):
        """注册定时任务"""
        self.scheduler.add_job(
            aggregate_usage_stats,
            IntervalTrigger(hours=1),
            id='aggregate_usage',
            kwargs={'days_back': 7},
            replace_existing=True,
        )
        logger.info("已注册定时任务: aggregate_usage (每小时)")

        self.scheduler.add_job(
            cleanup_telemetry,
            CronTrigger(hour=3, minute=0),
            id='cleanup_telemetry',
            kwargs={'retention_days': 90},
            replace_existing=True,
        )
        logger.info("已注册定时任务: cleanup_telemetry (每天 03:00)")

        self.scheduler.add_job(
            cleanup_main_db,
            CronTrigger(hour=3, minute=30),
            id='cleanup_main_db',
            kwargs={'audit_retention_days': 90, 'sync_retention_days': 90,
                    'result_retention_days': 30},
            replace_existing=True,
        )
        logger.info("已注册定时任务: cleanup_main_db (每天 03:30)")

        self.scheduler.add_job(
            wal_checkpoint,
            CronTrigger(hour=4, minute=0),
            id='wal_checkpoint',
            replace_existing=True,
        )
        logger.info("已注册定时任务: wal_checkpoint (每天 04:00)")

        self.scheduler.add_job(
            run_scheduled_syncs,
            IntervalTrigger(minutes=10),
            id='run_scheduled_syncs',
            replace_existing=True,
        )
        logger.info("已注册定时任务: run_scheduled_syncs (每 10 分钟)")

    def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("调度器已启动")

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")


scheduler_manager = SchedulerManager()
