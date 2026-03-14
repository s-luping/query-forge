# -*- coding: utf-8 -*-
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from scheduler.jobs import scheduled_task_example


class SchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    def init_scheduler(self):
        """初始化调度任务"""
        pass
        # 示例：每5分钟执行一次
        # self.scheduler.add_job(
        #     scheduled_task_example,
        #     'interval',
        #     minutes=1,
        #     id='example_task',
        #     kwargs={'say': 'Hello, World!'},
        # )

        # 示例：每天凌晨执行
        # self.scheduler.add_job(
        #     scheduled_task_example,
        #     CronTrigger(hour=0, minute=0),
        #     id='daily_task'
        # )

    def start(self):
        """启动调度器"""
        self.scheduler.start()

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown()


scheduler_manager = SchedulerManager()
