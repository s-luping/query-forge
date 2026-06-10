# -*- coding: UTF-8 -*-
"""
对话 API 路由 — 支持多轮连续对话 SQL 生成
"""
import json
from typing import Optional, cast

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth import get_current_user
from app.logger import logger
from core.LLMClient import LLMClient
from core.SQLGenerator import SqlGenerator
from core.ChatSession import ChatSession
from models import ConversationSessionLocal
from models.conversation import Conversation, ConversationMessage

router = APIRouter()

sql_generator = SqlGenerator()


# ── Pydantic models ──────────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    query: str
    schema_name: Optional[str] = None
    db_type: str = "sqlite"
    llm_config_id: Optional[int] = None
    knowledge_id: Optional[int] = None


class SendMessageRequest(BaseModel):
    content: str


class ConversationItem(BaseModel):
    id: int
    title: Optional[str]
    schema_name: Optional[str]
    db_type: str
    created_at: str
    updated_at: str
    message_count: int


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    sql: Optional[str]
    is_valid: bool
    error_message: Optional[str]
    columns: Optional[list]
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────

def _get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置"""
    from models import AppSessionLocal
    from models.llm import LLMConfig

    db = AppSessionLocal()
    try:
        if config_id:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.is_active == True,
                (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)
            ).first()
        else:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True,
                LLMConfig.is_active == True
            ).first()

        if config:
            return {
                'provider': config.provider,
                'model': config.model,
                'api_key': config.api_key,
                'base_url': config.base_url,
                'max_tokens': config.max_tokens or 8000,
                'temperature': config.temperature or 0.7,
                'timeout': config.timeout or 300
            }
        return None
    finally:
        db.close()


def _build_llm_client(user_id: int, llm_config_id: Optional[int] = None) -> LLMClient:
    """构建 LLM 客户端"""
    llm_config = _get_user_llm_config(user_id, llm_config_id)

    if llm_config:
        llm_client = LLMClient(
            provider=llm_config['provider'],
            api_key=llm_config['api_key'],
            model=llm_config['model'],
            base_url=llm_config.get('base_url'),
            max_tokens=llm_config['max_tokens'],
            timeout=llm_config['timeout'],
            temperature=llm_config['temperature']
        )
    else:
        llm_client = LLMClient()

    return llm_client


def _safe_parse_columns(raw) -> Optional[list]:
    """安全解析 columns JSON，兼容历史脏数据（字符串被误存为 JSON 字符串）"""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        # 历史 bug：可能存成了普通字符串
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _save_llm_log(user_id: int, provider: str, question: str, model: str, conditions: str,
                  result: str, duration_ms: float, prompt_tokens: int,
                  completion_tokens: int, total_tokens: int,
                  status: str = 'success', error_message: Optional[str] = None,
                  conversation_id: Optional[int] = None,
                  system_prompt: Optional[str] = None):
    """保存LLM调用记录"""
    from models import LLMSessionLocal
    from models.llm import LLMLog

    db = LLMSessionLocal()
    try:
        log = LLMLog(
            user_id=user_id,
            conversation_id=conversation_id,
            provider=provider,
            question=question,
            model=model,
            conditions=conditions,
            system_prompt=system_prompt,
            result=result,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status=status,
            error_message=error_message
        )
        db.add(log)
        db.commit()
        logger.info(f"LLM调用记录已保存: user_id={user_id}, conversation_id={conversation_id}, model={model}")
    except Exception as e:
        logger.error(f"保存LLM调用记录失败: {e}")
        db.rollback()
    finally:
        db.close()


def _get_extra_knowledge_safe(user_id: int, knowledge_id: Optional[int] = None) -> str:
    """获取补充知识（安全版本，失败返回空字符串）"""
    if not knowledge_id:
        return ""
    try:
        from app.routers.extra_router import get_extra_knowledge_safe
        knowledge = get_extra_knowledge_safe(user_id, knowledge_id)
        return knowledge.get("extra_knowledge", "") if knowledge else ""
    except Exception:
        return ""


# ── API Endpoints ─────────────────────────────────────────────────

@router.post("")
def create_conversation(
    request: CreateConversationRequest,
    user=Depends(get_current_user)
):
    """创建新对话 + 首轮 SQL 生成"""
    user_id = user['user_id']

    try:
        llm_client = _build_llm_client(user_id, request.llm_config_id)
        extra_knowledge = _get_extra_knowledge_safe(user_id, request.knowledge_id)

        session = ChatSession(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator
        )

        # 第一轮：走完整流水线
        result = session.process_first_message(
            query=request.query,
            schema_name=request.schema_name,
            db_type=request.db_type,
            extra_knowledge=extra_knowledge
        )

        # 保存到数据库
        db = ConversationSessionLocal()
        try:
            title = request.query[:80] + ("..." if len(request.query) > 80 else "")

            conversation = Conversation(
                user_id=user_id,
                title=title,
                schema_name=request.schema_name,
                db_type=request.db_type,
                llm_config_id=request.llm_config_id,
                knowledge_id=request.knowledge_id
            )
            db.add(conversation)
            db.flush()

            # 用户消息
            user_msg = ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=request.query
            )
            db.add(user_msg)

            # 助手消息
            columns_json = json.dumps(result.get('columns') or [], ensure_ascii=False)
            assistant_msg = ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=result.get('raw_response', result['sql']),
                sql=result['sql'],
                is_valid=result['is_valid'],
                error_message=result.get('error_message'),
                columns=columns_json
            )
            db.add(assistant_msg)
            db.commit()

            # 保存 schema_csv 到会话（存储在 conversation 的 title 字段不够，用消息的 content 存不下...）
            # schema_csv 存在消息元数据中：我们在 assistant 消息的 content 里不太合适
            # 用第一个 assist message 的 content 就够了——实际上 schema_csv 需要单独存
            # 简单方案：把 schema_csv 存在 conversation 的 title 之后再取用
            # 更好方案：这里把它存在第一个 assistant 的某个字段，或者新增字段
            # 当前：把 schema_csv 打包在 assistant content 的前缀（解析时去掉）
            # 实际实现：在 process_first_message 返回 schema_csv，我们存在...
            # 最简单：直接存到 assistant_msg 的一个已有字段，暂无。我们加个约定：
            # 在后续查询时重新从 schema 构建。或者——最好的办法是从第一轮的 pipeline 结果重建。
            # 当前方案：传给 followup 时从 DB 的 schema 重新构建 CSV。
            # 这没问题，因为 schema 数据在 sys_schema.db 中持久化了。

            conversation_id = cast(int, conversation.id)
            assistant_msg_id = cast(int, assistant_msg.id)

        finally:
            db.close()

        # 保存 LLM 调用记录
        tokens = result.get('tokens', {})
        messages = result.get('messages', [])
        system_prompt_text = messages[0]['content'] if messages else ''
        _save_llm_log(
            user_id=user_id,
            provider=llm_client.provider,
            question=request.query,
            model=llm_client.model,
            conditions=f"schema={request.schema_name}, db_type={request.db_type}",
            result=result['sql'],
            duration_ms=result.get('duration_ms', 0),
            prompt_tokens=tokens.get('prompt_tokens', 0),
            completion_tokens=tokens.get('completion_tokens', 0),
            total_tokens=tokens.get('total_tokens', 0),
            status='success' if result['is_valid'] else 'warning',
            error_message=result.get('error_message') if not result['is_valid'] else None,
            conversation_id=conversation_id,
            system_prompt=system_prompt_text
        )

        logger.info(f"对话创建成功: id={conversation_id}, user_id={user_id}")

        return {
            "conversation": {
                "id": conversation_id,
                "title": title,
                "schema_name": request.schema_name,
                "db_type": request.db_type
            },
            "message": {
                "id": assistant_msg_id,
                "role": "assistant",
                "sql": result['sql'],
                "is_valid": result['is_valid'],
                "error_message": result.get('error_message'),
                "columns": result.get('columns'),
                "raw_response": result.get('raw_response', ''),
                "tokens": result.get('tokens', {})
            }
        }

    except Exception as e:
        logger.error(f"创建对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建对话失败: {str(e)}")


@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    user=Depends(get_current_user)
):
    """发送跟进消息 + 生成修正 SQL"""
    user_id = user['user_id']

    try:
        db = ConversationSessionLocal()
        try:
            # 验证对话归属
            conversation = db.query(Conversation).filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            ).first()
            if not conversation:
                raise HTTPException(status_code=404, detail="对话不存在")

            # 获取历史消息
            history = db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).order_by(ConversationMessage.created_at.asc()).all()

            if not history:
                raise HTTPException(status_code=400, detail="对话无历史消息")

            # 从 schema 数据库重建 schema CSV（用于 context）
            schema_csv = _rebuild_schema_csv(user_id, conversation.schema_name)

            # 复用对话创建时的模型配置
            llm_client = _build_llm_client(user_id, conversation.llm_config_id)

            session = ChatSession(
                user_id=user_id,
                llm_client=llm_client,
                sql_generator=sql_generator
            )

            # 跟进消息
            extra_knowledge = _get_extra_knowledge_safe(user_id, conversation.knowledge_id)
            result = session.process_followup_message(
                conversation_messages=history,
                new_user_content=request.content,
                schema_csv=schema_csv,
                db_type=conversation.db_type,
                extra_knowledge=extra_knowledge
            )

            # 保存消息
            user_msg = ConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content=request.content
            )
            db.add(user_msg)

            columns_json = json.dumps(result.get('columns') or [], ensure_ascii=False)
            assistant_msg = ConversationMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=result.get('raw_response', result['sql']),
                sql=result['sql'],
                is_valid=result['is_valid'],
                error_message=result.get('error_message'),
                columns=columns_json
            )
            db.add(assistant_msg)

            # 更新会话时间
            from datetime import datetime
            conversation.updated_at = datetime.now()

            db.commit()

            user_msg_id = user_msg.id
            assistant_msg_id = assistant_msg.id

        finally:
            db.close()

        # 保存 LLM 调用记录
        tokens = result.get('tokens', {})
        messages = result.get('messages', [])
        system_prompt_text = messages[0]['content'] if messages else ''
        _save_llm_log(
            user_id=user_id,
            provider=llm_client.provider,
            question=request.content,
            model=llm_client.model,
            conditions=f"conversation={conversation_id}, followup",
            result=result['sql'],
            duration_ms=result.get('duration_ms', 0),
            prompt_tokens=tokens.get('prompt_tokens', 0),
            completion_tokens=tokens.get('completion_tokens', 0),
            total_tokens=tokens.get('total_tokens', 0),
            status='success' if result['is_valid'] else 'warning',
            error_message=result.get('error_message') if not result['is_valid'] else None,
            conversation_id=conversation_id,
            system_prompt=system_prompt_text
        )

        logger.info(f"对话消息已发送: conversation_id={conversation_id}")

        return {
            "user_message": {
                "id": user_msg_id,
                "role": "user",
                "content": request.content
            },
            "assistant_message": {
                "id": assistant_msg_id,
                "role": "assistant",
                "sql": result['sql'],
                "is_valid": result['is_valid'],
                "error_message": result.get('error_message'),
                "columns": result.get('columns'),
                "raw_response": result.get('raw_response', ''),
                "tokens": result.get('tokens', {})
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@router.get("")
def list_conversations(
    user=Depends(get_current_user)
):
    """获取对话列表（管理员看全部，用户看自己）"""
    user_id = user['user_id']
    is_admin = user.get('role') == 'admin'

    db = ConversationSessionLocal()
    try:
        query = db.query(Conversation)
        if not is_admin:
            query = query.filter(Conversation.user_id == user_id)
        conversations = query.order_by(Conversation.updated_at.desc()).all()

        result = []
        for conv in conversations:
            msg_count = db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conv.id
            ).count()
            result.append(ConversationItem(
                id=conv.id,
                title=conv.title,
                schema_name=conv.schema_name,
                db_type=conv.db_type or "sqlite",
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
                message_count=msg_count
            ))

        return result
    finally:
        db.close()


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    user=Depends(get_current_user)
):
    """获取对话消息历史"""
    user_id = user['user_id']

    db = ConversationSessionLocal()
    try:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).order_by(ConversationMessage.created_at.asc()).all()

        return [
            MessageItem(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                sql=msg.sql,
                is_valid=msg.is_valid,
                error_message=msg.error_message,
                columns=_safe_parse_columns(msg.columns),
                created_at=msg.created_at.isoformat() if msg.created_at else ""
            )
            for msg in messages
        ]
    finally:
        db.close()


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    user=Depends(get_current_user)
):
    """删除对话"""
    user_id = user['user_id']

    db = ConversationSessionLocal()
    try:
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id
        ).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")

        # 删除关联消息
        db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).delete()

        db.delete(conversation)
        db.commit()

        return {"success": True, "message": "对话已删除"}
    finally:
        db.close()


# ── Internal helpers ──────────────────────────────────────────────

def _rebuild_schema_csv(user_id: int, schema_name: Optional[str] = None) -> str:
    """从数据库重建 schema CSV 字符串"""
    from models import SchemaSessionLocal
    from models.schema import Schema

    db = SchemaSessionLocal()
    try:
        query = db.query(Schema).filter(Schema.user_id == user_id)
        if schema_name:
            query = query.filter(Schema.schema_name == schema_name)
        items = query.all()

        if not items:
            return "表名,字段名,字段类型,字段描述,主键,外键"

        # 按表分组
        tables = {}
        for s in items:
            if s.table_name not in tables:
                tables[s.table_name] = []
            tables[s.table_name].append(s)

        lines = ["表名,字段名,字段类型,字段描述,主键,外键"]
        for table_name, fields in tables.items():
            for f in fields:
                lines.append(
                    f"{table_name},{f.column_name or ''},"
                    f"{f.column_type or ''},"
                    f"{f.column_description or ''},"
                    f"{f.column_key or ''},"
                    f"{f.foreign_key or ''}"
                )

        return '\n'.join(lines)
    finally:
        db.close()
