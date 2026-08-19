# -*- coding: UTF-8 -*-
"""
对话 API 路由 — 支持多轮连续对话 SQL 生成

遥测对接：
- LLM 调用记录写入遥测库（services/llm/telemetry.record_call）
- assistant 消息通过 llm_call_id 关联调用明细（跨库逻辑引用）
- 首轮 schema 上下文 prompt 通过 conversation.context_prompt_id 关联去重 prompt
"""
import json
from datetime import datetime
from typing import Optional, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import CurrentUser
from app.logger import logger
from app.security.crypto import decrypt_secret
from core.llm import LLMClient
from core.generation.sql_generator import SqlGenerator
from core.generation.chat import ChatSession
from app.timezone import now_beijing
from models.conversation import Conversation, ConversationMessage
from services.llm import telemetry
from services.schema import service as schema_service
from services.sql.executor import execute_sql, SqlExecutionError
from curd.base import session_scope
from curd.conversation import conversation_crud
from curd.schema import schema_crud

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
    query_result: Optional[dict] = None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────

def _get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置（api_key 解密后供客户端使用）"""
    from models.llm import LLMConfig

    with session_scope() as db:
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
                'id': config.id,
                'provider': config.provider,
                'model': config.model,
                'api_key': decrypt_secret(config.api_key),
                'base_url': config.base_url,
                'max_tokens': config.max_tokens or 8000,
                'temperature': config.temperature or 0.7,
                'timeout': config.timeout or 300
            }
        return None
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
    """安全解析 columns JSON，兼容历史脏数据"""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _safe_parse_result(raw) -> Optional[dict]:
    """安全解析 result_data JSON（查询结果持久化）"""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _get_knowledge_safe(user_id: int, knowledge_id: Optional[int] = None) -> str:
    """获取知识内容（安全版本，失败返回空字符串）"""
    if not knowledge_id:
        return ""
    try:
        from app.routers.knowledge_router import get_knowledge_safe
        knowledge = get_knowledge_safe(user_id, knowledge_id)
        return knowledge.get("content", "") if knowledge else ""
    except Exception:
        return ""


def _record_telemetry(user_id: int, llm_client: LLMClient, question: str,
                      conditions: str, result: dict, conversation_id: Optional[int],
                      config_id: Optional[int], purpose: str = 'chat_sql') -> Optional[int]:
    """把一次 LLM 调用写入遥测库（永不抛异常），返回 llm_call_id"""
    tokens = result.get('tokens', {})
    messages = result.get('messages', [])
    system_prompt_text = messages[0]['content'] if messages else None
    return telemetry.record_call(
        user_id=user_id,
        provider=llm_client.provider,
        question=question,
        model=llm_client.model,
        conditions=conditions,
        result=result.get('sql', ''),
        duration_ms=result.get('duration_ms', 0),
        prompt_tokens=tokens.get('prompt_tokens', 0),
        completion_tokens=tokens.get('completion_tokens', 0),
        total_tokens=tokens.get('total_tokens', 0),
        status='success' if result.get('is_valid') else 'warning',
        error_message=result.get('error_message') if not result.get('is_valid') else None,
        conversation_id=conversation_id,
        config_id=config_id,
        purpose=purpose,
        system_prompt=system_prompt_text,
    )


# ── API Endpoints ─────────────────────────────────────────────────

def _execute_generated_sql(sql: str, schema_name: Optional[str],
                           db_type: str) -> dict:
    """执行生成的 SQL 并返回查询结果；SQL 为空或执行失败时返回错误信息。

    查询前校验 SQL 非空；仅允许 SELECT（执行器内部二次校验）。
    """
    if not sql or not sql.strip():
        return {"error": "生成的 SQL 为空，未执行查询", "columns": [], "rows": [], "row_count": 0}
    try:
        return execute_sql(sql, schema_name=schema_name, db_type=db_type)
    except SqlExecutionError as e:
        return {"error": str(e), "columns": [], "rows": [], "row_count": 0}


@router.post("")
def create_conversation(
    request: CreateConversationRequest,
    user: CurrentUser
):
    """创建新对话 + 首轮 SQL 生成"""
    user_id = user['user_id']

    # 库级可见性二次校验（防绕过前端下拉直接请求无权限库）
    from app.permissions import is_schema_visible
    if not is_schema_visible(user, request.schema_name):
        raise HTTPException(status_code=403, detail="无权访问该数据库")

    # 数据库类型以所选库存储的类型为准（选库后无需再手动选类型）；
    # 库未设置类型时才回退请求参数
    db_type = request.db_type
    if request.schema_name:
        with session_scope() as db_cfg:
            db_type = schema_service.get_schema_type_by_name(
                db_cfg, request.schema_name) or db_type

    try:
        llm_client = _build_llm_client(user_id, request.llm_config_id)
        knowledge_content = _get_knowledge_safe(user_id, request.knowledge_id)

        session = ChatSession(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator,
            user=user
        )

        # 第一轮：走完整流水线
        result = session.process_first_message(
            query=request.query,
            schema_name=request.schema_name,
            db_type=db_type,
            knowledge_content=knowledge_content
        )

        # 执行生成的 SQL：查询前校验非空，直接查库返回结果
        query_result = _execute_generated_sql(
            result.get('sql', ''), request.schema_name, db_type)

        # 保存到数据库
        with session_scope() as db:
            title = request.query[:80] + ("..." if len(request.query) > 80 else "")
    
            schema_id = schema_service.get_schema_id_by_name(db, request.schema_name)
    
            conversation = Conversation(
                user_id=user_id,
                title=title,
                schema_id=schema_id,
                db_type=db_type,
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
                columns=columns_json,
                result_data=json.dumps(query_result, ensure_ascii=False) if query_result else None
            )
            db.add(assistant_msg)
            db.flush()

            # flush 后 id 已分配，先取回再 commit（避免 commit expire 后属性刷新异常）
            conversation_id = cast(int, conversation.id)
            assistant_msg_id = cast(int, assistant_msg.id)
            db.commit()
        # 保存 LLM 调用记录（遥测库）+ 回填关联键（主库）
        call_id = _record_telemetry(
            user_id, llm_client, request.query,
            conditions=f"schema={request.schema_name}, db_type={request.db_type}",
            result=result, conversation_id=conversation_id,
            config_id=request.llm_config_id)

        prompt_text = (result.get('messages') or [{}])[0].get('content')
        prompt_id = telemetry.get_or_create_prompt(prompt_text) if prompt_text else None

        if call_id or prompt_id:
            conversation_crud.bind_telemetry(conversation_id, assistant_msg_id, call_id, prompt_id)
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
                "tokens": result.get('tokens', {}),
                "query_result": query_result
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建对话失败: {str(e)}")


@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    user: CurrentUser
):
    """发送跟进消息 + 生成修正 SQL"""
    user_id = user['user_id']

    try:
        with session_scope() as db:
            # 验证对话归属
            conversation = db.query(Conversation).filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            ).first()
            if not conversation:
                raise HTTPException(status_code=404, detail="对话不存在")
    
            # 获取历史消息（转 dict 供会话外使用，避免 detached ORM 对象）
            history = [{
                'role': m.role,
                'content': m.content or '',
                'sql': m.sql,
            } for m in db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).order_by(ConversationMessage.created_at.asc()).all()]
    
            if not history:
                raise HTTPException(status_code=400, detail="对话无历史消息")
    
            schema_name = schema_service.get_schema_name_by_id(db, conversation.schema_id)
            conv_db_type = conversation.db_type
            conv_llm_config_id = conversation.llm_config_id
            conv_knowledge_id = conversation.knowledge_id
        # 从三层模型重建 schema CSV（用于 context）
        schema_csv = _rebuild_schema_csv(schema_name)

        llm_client = _build_llm_client(user_id, conv_llm_config_id)

        session = ChatSession(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator,
            user=user
        )

        # 跟进消息
        knowledge_content = _get_knowledge_safe(user_id, conv_knowledge_id)
        result = session.process_followup_message(
            conversation_messages=history,
            new_user_content=request.content,
            schema_csv=schema_csv,
            db_type=conv_db_type,
            schema_name=schema_name,
            knowledge_content=knowledge_content
        )

        # 执行生成的 SQL：查询前校验非空，直接查库返回结果
        query_result = _execute_generated_sql(
            result.get('sql', ''), schema_name, conv_db_type)

        # 保存消息
        with session_scope() as db:
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
                columns=columns_json,
                result_data=json.dumps(query_result, ensure_ascii=False) if query_result else None
            )
            db.add(assistant_msg)
            db.flush()
    
            # 更新会话时间
            db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).update({'updated_at': now_beijing()})
    
            # flush 后 id 已分配，先取回再 commit（避免 commit expire 后属性刷新异常）
            user_msg_id = user_msg.id
            assistant_msg_id = assistant_msg.id
            db.commit()
        # 保存 LLM 调用记录（遥测库）+ 回填消息关联
        call_id = _record_telemetry(
            user_id, llm_client, request.content,
            conditions=f"conversation={conversation_id}, followup",
            result=result, conversation_id=conversation_id,
            config_id=conv_llm_config_id)

        telemetry.bind_message(call_id, conversation_id, assistant_msg_id)

        if call_id:
            with session_scope() as db:
                db.query(ConversationMessage).filter(
                    ConversationMessage.id == assistant_msg_id
                ).update({'llm_call_id': call_id})
                db.commit()
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
                "tokens": result.get('tokens', {}),
                "query_result": query_result
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@router.get("")
def list_conversations(
    user: CurrentUser
):
    """获取对话列表（管理员看全部，用户看自己）"""
    user_id = user['user_id']
    is_admin = user.get('role') == 'admin'

    conversations = conversation_crud.list_all() if is_admin else conversation_crud.list_by_user(user_id)
    # schema id → name 映射（一次查询）
    schema_names = schema_crud.name_map()
    # 各对话消息数（一次 GROUP BY 聚合，避免 N+1 count）
    from curd.conversation import message_crud
    from sqlalchemy import func
    with session_scope() as db:
        conv_ids = [c.id for c in conversations]
        msg_counts = dict(db.query(ConversationMessage.conversation_id, func.count(ConversationMessage.id))
                          .filter(ConversationMessage.conversation_id.in_(conv_ids))
                          .group_by(ConversationMessage.conversation_id).all()) if conv_ids else {}

    result = []
    for conv in conversations:
        result.append(ConversationItem(
            id=conv.id,
            title=conv.title,
            schema_name=schema_names.get(conv.schema_id),
            db_type=conv.db_type or "sqlite",
            created_at=conv.created_at.isoformat() if conv.created_at else "",
            updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
            message_count=msg_counts.get(conv.id, 0)
        ))

    return result
@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    user: CurrentUser
):
    """获取对话消息历史"""
    user_id = user['user_id']

    with session_scope() as db:
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
                query_result=_safe_parse_result(msg.result_data),
                created_at=msg.created_at.isoformat() if msg.created_at else ""
            )
            for msg in messages
        ]
@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    user: CurrentUser
):
    """删除对话"""
    user_id = user['user_id']

    with session_scope() as db:
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
# ── Internal helpers ──────────────────────────────────────────────

def _rebuild_schema_csv(schema_name: Optional[str] = None) -> str:
    """从三层模型重建 schema CSV 字符串（字段召回上下文）"""
    rows = schema_service.iter_field_rows(schema_name=schema_name)

    if not rows:
        return "表名,字段名,字段类型,字段描述,主键,外键"

    # 按表分组（iter_field_rows 已按表连续返回，仍做稳定分组）
    tables = {}
    for f in rows:
        tables.setdefault(f.table_name, []).append(f)

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
