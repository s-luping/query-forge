"""QueryForge 统一时间工具，所有系统时间使用北京时间。"""
from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


def now_beijing() -> datetime:
    """返回无时区的北京时间，适用于现有 SQLite DateTime 字段。"""
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def now_beijing_aware() -> datetime:
    """返回带时区的北京时间，适用于 JWT 等需要明确时区的场景。"""
    return datetime.now(BEIJING_TZ)
