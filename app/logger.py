"""
日志系统 — 按类型分离（统一写入 logs/，自动轮转）
  app.log      应用日志（请求、认证、业务）
  llm.log      大模型调用详情
  audit.log    审计日志（写操作、权限变更）
  server.log   服务日志（uvicorn 启动/访问，按天轮转保留30天，由 main.py 配置）

说明：SQL 生成过程（pipeline）链路追踪已改为写入数据库 QueryAuditLog.pipeline_log 字段，
      供前端「链路追踪」弹窗展示，不再单独输出文件日志；
      数据库异常统一走 app.log（WARNING 以上），不再单独维护 sqlalchemy 日志。
"""
import logging
import os
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

from app.timezone import BEIJING_TZ

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


class BeijingFormatter(logging.Formatter):
    """使用北京时间格式化日志时间。"""
    converter = staticmethod(lambda timestamp: datetime.fromtimestamp(
        timestamp, BEIJING_TZ).timetuple())


def _create_logger(name, filename, level=logging.INFO, fmt=None, console=False,
                   backup_count=5):
    log_logger = logging.getLogger(name)
    log_logger.setLevel(level)
    log_logger.propagate = False
    # backupCount=5：达到 maxBytes 后轮转，保留最近 5 个历史文件（每个 10MB）
    handler = RotatingFileHandler(os.path.join(LOG_DIR, filename),
                                  maxBytes=10 * 1024 * 1024, backupCount=backup_count,
                                  encoding="utf-8")
    handler.setFormatter(BeijingFormatter(
        fmt or "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    log_logger.addHandler(handler)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(handler.formatter)
        log_logger.addHandler(ch)
    return log_logger


logger = _create_logger("app", "app.log", fmt="%(asctime)s [%(levelname)s] %(module)s: %(message)s", console=True)
llm_logger = _create_logger("llm", "llm.log", level=logging.DEBUG, fmt="%(asctime)s\n%(message)s\n" + "=" * 80)
audit_logger = _create_logger("audit", "audit.log", fmt="%(asctime)s | %(message)s")


def setup_server_logging():
    """将 Uvicorn 日志按天写入 server.log，同时保留控制台输出。"""
    handler = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, 'server.log'), when='midnight',
        backupCount=30, encoding='utf-8')
    handler.setFormatter(BeijingFormatter('%(asctime)s | %(levelname)s | %(message)s'))
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        uvicorn_logger = logging.getLogger(name)
        if not any(isinstance(existing, TimedRotatingFileHandler)
                   for existing in uvicorn_logger.handlers):
            uvicorn_logger.addHandler(handler)


def log_error(e: Exception, ctx: str = ""):
    """记录异常和堆栈"""
    msg = f"{ctx}: {e}" if ctx else str(e)
    logger.error(f"{msg}\n{traceback.format_exc()}")


def log_audit(user: dict, action: str, detail: str = "", target: str = ""):
    """审计日志：用户 + 操作 + 目标 + 详情"""
    uid = user.get('user_id', '?')
    uname = user.get('username', '?')
    parts = [f"user={uid}({uname})", f"action={action}"]
    if target: parts.append(f"target={target}")
    if detail: parts.append(detail)
    audit_logger.info(" | ".join(parts))
    logger.info(f"[AUDIT] {' | '.join(parts)}")
