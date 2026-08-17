"""
日志系统 — 按类型分离
  app.log      应用日志（请求、认证、业务）
  llm.log      大模型调用详情
  pipeline.log SQL生成过程
  sqlalchemy.log  数据库查询
  audit.log    审计日志（写操作、权限变更）
"""
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def _create_logger(name, filename, level=logging.INFO, fmt=None, console=False):
    log_logger = logging.getLogger(name)
    log_logger.setLevel(level)
    log_logger.propagate = False
    handler = RotatingFileHandler(os.path.join(LOG_DIR, filename), maxBytes=10 * 1024 * 1024, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
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
pipeline_logger = _create_logger("pipeline", "pipeline.log", level=logging.DEBUG, fmt="%(asctime)s\n%(message)s\n" + "=" * 80)
# sqlalchemy 仅记录 WARNING 以上（不再每句 SQL 都写日志，避免日志无限膨胀）
sqlalchemy_logger = _create_logger("sqlalchemy.engine", "sqlalchemy.log",
                                   level=logging.WARNING, fmt="%(asctime)s %(message)s")
audit_logger = _create_logger("audit", "audit.log", fmt="%(asctime)s | %(message)s")


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
