# -*- coding: UTF-8 -*-
"""LLM 调用遥测服务 — 明细层 llm_calls + 去重层 llm_prompts

设计要点：
- system_prompt 大文本按 SHA-256 去重存入 llm_prompts，N 次相同上下文只存一份
- record_call() 永不抛异常（遥测失败不影响业务主流程）
- 聚合层 llm_usage_stats 由 scheduler/jobs/usage_stats.py 定时刷新
"""
import hashlib
from typing import Optional

from app.logger import logger
from crud.base import session_scope
from models.llm import LLMCall, LLMPrompt


def get_or_create_prompt(content: Optional[str]) -> Optional[int]:
    """prompt 去重存储，返回 prompt_id（内容为空返回 None）"""
    if not content:
        return None
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    try:
        with session_scope(telemetry=True) as db:
            row = db.query(LLMPrompt).filter(LLMPrompt.content_hash == content_hash).first()
            if row:
                return row.id
            prompt = LLMPrompt(content_hash=content_hash, content=content, length=len(content))
            db.add(prompt)
            db.flush()   # 立即取回自增 id
            return prompt.id
    except Exception:
        return None


def record_call(
    user_id: int,
    provider: str,
    question: str,
    model: str,
    conditions: str = '',
    result: str = '',
    duration_ms: float = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    reasoning_tokens: int = 0,
    total_tokens: int = 0,
    status: str = 'success',
    error_message: Optional[str] = None,
    conversation_id: Optional[int] = None,
    message_id: Optional[int] = None,
    config_id: Optional[int] = None,
    purpose: str = 'chat_sql',
    system_prompt: Optional[str] = None,
    cost: float = 0.0,
) -> Optional[int]:
    """记录一次 LLM 调用（永不抛异常），返回 llm_calls.id"""
    try:
        prompt_id = get_or_create_prompt(system_prompt)
    except Exception:
        prompt_id = None

    try:
        with session_scope(telemetry=True) as db:
            call = LLMCall(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                config_id=config_id,
                provider=provider or '',
                model=model or 'unknown',
                purpose=purpose,
                question=question,
                conditions=conditions,
                prompt_id=prompt_id,
                result=result,
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                reasoning_tokens=reasoning_tokens or 0,
                total_tokens=total_tokens or 0,
                cost=cost or 0.0,
                status=status,
                error_message=error_message,
            )
            db.add(call)
            db.flush()   # 立即取回自增 id
            logger.info(f"LLM调用已记录: user_id={user_id}, model={model}, purpose={purpose}")
            return call.id
    except Exception as e:
        logger.error(f"保存LLM调用记录失败: {e}")
        return None


def bind_message(call_id: Optional[int], conversation_id: Optional[int], message_id: Optional[int]):
    """把已落库的调用回填到消息关联键（关联层）"""
    if not call_id:
        return
    try:
        with session_scope(telemetry=True) as db:
            call = db.query(LLMCall).filter(LLMCall.id == call_id).first()
            if call:
                call.conversation_id = conversation_id
                call.message_id = message_id
    except Exception as e:
        logger.error(f"回填消息关联失败: {e}")


def get_prompt_content(prompt_id: Optional[int]) -> Optional[str]:
    if not prompt_id:
        return None
    with session_scope(telemetry=True) as db:
        row = db.query(LLMPrompt).filter(LLMPrompt.id == prompt_id).first()
        return row.content if row else None