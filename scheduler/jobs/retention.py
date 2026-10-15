# -*- coding: UTF-8 -*-
"""遥测数据保留清理任务 — 定期删除过期的 llm_calls 和孤立 llm_prompts

默认保留 90 天，由 scheduler 每天凌晨执行一次。
"""
from datetime import timedelta

from sqlalchemy import text

from app.logger import logger
from app.timezone import now_beijing
from crud.base import session_scope
from db.engine import engine_logs, engine_main, engine_telemetry, is_sqlite
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


def cleanup_logs_db(audit_retention_days: int = 90,
                    sync_retention_days: int = 90) -> dict:
    """清理日志库过期数据 — 堵住三张无上限增长表

    步骤：
      1. 删除 query_audit_logs 中早于 audit_retention_days 的记录
      2. 删除 sync_run_logs / schema_change_logs 中早于 sync_retention_days 的记录

    注意：删除顺序先 change_logs 后 run_logs，避免外键约束（change 引用 run）报错。

    Args:
        audit_retention_days: 审计日志保留天数（默认 90）
        sync_retention_days: 同步历史/变更记录保留天数（默认 90）

    Returns:
        {"audit_deleted": int, "changes_deleted": int, "runs_deleted": int}
    """
    from models.security import QueryAuditLog
    from models.sync import SchemaChangeLog, SyncRunLog

    audit_cutoff = now_beijing() - timedelta(days=audit_retention_days)
    sync_cutoff = now_beijing() - timedelta(days=sync_retention_days)
    result = {"audit_deleted": 0, "changes_deleted": 0, "runs_deleted": 0}

    try:
        with session_scope(logs=True) as db:
            # 1. 过期审计日志
            result["audit_deleted"] = db.query(QueryAuditLog).filter(
                QueryAuditLog.created_at < audit_cutoff
            ).delete(synchronize_session=False)

            # 2. 同步变更记录 → 执行历史（先子后父，规避外键）
            result["changes_deleted"] = db.query(SchemaChangeLog).filter(
                SchemaChangeLog.created_at < sync_cutoff
            ).delete(synchronize_session=False)
            result["runs_deleted"] = db.query(SyncRunLog).filter(
                SyncRunLog.started_at < sync_cutoff
            ).delete(synchronize_session=False)

        logger.info(
            f"cleanup_logs_db: 审计 {result['audit_deleted']} 条，"
            f"变更 {result['changes_deleted']} 条，同步历史 {result['runs_deleted']} 条"
            f"（审计/同步保留 {sync_retention_days} 天）"
        )
        return result
    except Exception as e:
        logger.error(f"cleanup_logs_db 失败: {e}")
        result["error"] = str(e)
        return result


def cleanup_main_db(result_retention_days: int = 30) -> dict:
    """清理主库过期数据 — 清空对话消息里的大 JSON 查询结果

    步骤：
      清空 conversation_messages.result_data 中早于 result_retention_days 的查询结果
      （只清结果 JSON，不删对话历史；结果可从源库重新执行获得）

    Args:
        result_retention_days: 对话查询结果 JSON 保留天数（默认 30）

    Returns:
        {"results_cleared": int}
    """
    from models.conversation import ConversationMessage

    result_cutoff = now_beijing() - timedelta(days=result_retention_days)
    result = {"results_cleared": 0}

    try:
        with session_scope() as db:
            # 清空过期查询结果（保留对话记录本身，仅释放大 JSON）
            result["results_cleared"] = db.query(ConversationMessage).filter(
                ConversationMessage.created_at < result_cutoff,
                ConversationMessage.result_data.isnot(None),
            ).update({ConversationMessage.result_data: None},
                     synchronize_session=False)

        logger.info(
            f"cleanup_main_db: 查询结果 {result['results_cleared']} 条"
            f"（结果保留 {result_retention_days} 天）"
        )
        return result
    except Exception as e:
        logger.error(f"cleanup_main_db 失败: {e}")
        result["error"] = str(e)
        return result


def wal_checkpoint() -> dict:
    """执行 SQLite WAL checkpoint，回收 WAL 文件体积

    长期运行下 WAL 会随写入持续增大（queryforge.db-wal 已远大于主库文件），
    每日执行一次 TRUNCATE 模式的 checkpoint 将其合并回主库文件。
    MySQL/PostgreSQL 模式跳过（无 WAL 概念）。
    """
    if not is_sqlite:
        return {"skipped": True, "reason": "非 SQLite 模式"}

    result = {"main_truncated": 0, "telemetry_truncated": 0, "logs_truncated": 0}
    try:
        # 主库 / 遥测库 / 日志库均为独立 SQLite 文件，需各自 checkpoint
        for key, engine in (("main_truncated", engine_main),
                            ("telemetry_truncated", engine_telemetry),
                            ("logs_truncated", engine_logs)):
            with engine.connect() as conn:
                row = conn.execute(
                    text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
                # row 形如 (busy, log, checkpointed)；checkpointed 为已回写页数
                result[key] = row[2] if row and len(row) > 2 else 0
        logger.info(f"wal_checkpoint: 主库回写 {result['main_truncated']} 页，"
                    f"遥测库回写 {result['telemetry_truncated']} 页，"
                    f"日志库回写 {result['logs_truncated']} 页")
        return result
    except Exception as e:
        logger.error(f"wal_checkpoint 失败: {e}")
        result["error"] = str(e)
        return result
