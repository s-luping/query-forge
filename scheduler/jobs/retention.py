# -*- coding: UTF-8 -*-
"""遥测数据保留清理任务 — 定期删除过期的 llm_calls 和孤立 llm_prompts

默认保留 90 天，由 scheduler 每天凌晨执行一次。
"""
from datetime import datetime, timedelta

from app.logger import logger
from app.timezone import now_beijing
from crud.base import session_scope
from models.llm import LLMCall, LLMPrompt


def cleanup_telemetry(retention_days: int = 90) -> dict:
    """清理过期的遥测数据

    步骤：
      1. 删除 llm_calls 中 created_at 早于 N 天前的记录
      2. 删除 llm_prompts 中不再被任何 llm_calls 引用的孤立记录

    Args:
        retention_days: 保留天数（默认 90）

    Returns:
        {"calls_deleted": int, "prompts_deleted": int}
    """
    cutoff = now_beijing() - timedelta(days=retention_days)
    try:
        with session_scope(telemetry=True) as db:
            # 1. 删除过期调用记录
            calls_deleted = db.query(LLMCall).filter(
                LLMCall.created_at < cutoff
            ).delete(synchronize_session=False)

            # 2. 删除孤立 prompt（不被任何 llm_call 引用）
            referenced_ids = db.query(LLMCall.prompt_id).filter(
                LLMCall.prompt_id.isnot(None)
            ).distinct().subquery()
            orphan_prompts = db.query(LLMPrompt).filter(
                ~LLMPrompt.id.in_(referenced_ids)
            )
            prompts_deleted = orphan_prompts.count()
            orphan_prompts.delete(synchronize_session=False)

        logger.info(
            f"cleanup_telemetry: 删除 {calls_deleted} 条过期调用记录，"
            f"{prompts_deleted} 条孤立 prompt（保留 {retention_days} 天）"
        )
        return {"calls_deleted": calls_deleted, "prompts_deleted": prompts_deleted}
    except Exception as e:
        logger.error(f"cleanup_telemetry 失败: {e}")
        return {"calls_deleted": 0, "prompts_deleted": 0, "error": str(e)}
