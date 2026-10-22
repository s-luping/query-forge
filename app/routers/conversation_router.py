# -*- coding: UTF-8 -*-
"""
对话 API 路由 — 支持多轮连续对话 SQL 生成

遥测对接：
- LLM 调用记录写入遥测库（services/llm/telemetry.record_call）
- assistant 消息通过 llm_call_id 关联调用明细（跨库逻辑引用）
- 首轮 schema 上下文 prompt 通过 conversation.context_prompt_id 关联去重 prompt
"""
import json
from typing import List, Optional, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth import CurrentUser
from app.crypto import decrypt_secret
from app.limiter import LIMIT_HEAVY, LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import logger
from app.response import ok, ok_msg
from app.timezone import now_beijing
from core import LLMClient
from core.llm_client import LLMArrearsError
from core.gen_chat import ChatSession, SchemaAuthError
from core.gen_sql import SqlGenerator
from core.ret_retriever import SchemaRetriever
from crud.base import session_scope
from crud.conversation import conversation_crud
from crud.schema import schema_crud
from models.conversation import Conversation, ConversationMessage
from services import schema_service, telemetry
from services.sql_executor import SqlExecutionError, execute_sql

router = APIRouter()

sql_generator = SqlGenerator()


# ── Pydantic models ──────────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    query: str
    schema_name: Optional[str] = None
    db_type: str = "sqlite"
    llm_config_id: Optional[int] = None
    knowledge_id: Optional[int] = None            # 兼容旧版单条
    knowledge_ids: Optional[List[int]] = None     # 多知识库


class SendMessageRequest(BaseModel):
    content: str
    # 对话过程中可随时切换模型 / 知识库（显式传值则切换并持久化；不传沿用会话配置）
    llm_config_id: Optional[int] = None
    knowledge_id: Optional[int] = None            # 兼容旧版单条
    knowledge_ids: Optional[List[int]] = None     # 多知识库


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
    llm_info: Optional[dict] = None
    permission_note: Optional[str] = None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────

def _permission_note(result: dict, query_result: Optional[dict] = None) -> Optional[str]:
    """从网关结果 + 执行结果提取用户可见的结果归因提示。

    覆盖三类静默行为，避免用户对结果产生误解：
    - 行级过滤注入（was_modified）：结果行数被悄悄裁剪，需明示过滤了哪些表
    - 敏感字段参与聚合（hit_sensitive）：FILTER 字段仅以聚合值返回，不暴露明细
    - 空结果归因：SQL 执行成功但 0 行时，结合权限过滤情况告知可能原因
      （此前用户只看到"共 0 行"，无法区分数据为空、条件过严还是权限过滤所致）
    拦截类提示已由 error_message 承载，此处不重复。
    """
    gw = result.get('gateway')
    parts = []
    # 权限裁剪提示（哪些字段/表被裁减）：权限明细步生成，无论生成与否都透出
    trimmed = (result.get('trimmed_notice') or '').strip()
    if trimmed:
        parts.append(trimmed)
    if gw:
        if gw.get('was_modified'):
            tables = []
            for m in (gw.get('modifications') or []):
                # 格式：'注入行级过滤: {table} → {filter_expr}'
                try:
                    name = m.split(':', 1)[1].split('→')[0].strip()
                    if name:
                        tables.append(name)
                except (IndexError, AttributeError):
                    continue
            if tables:
                parts.append(f"已按数据权限过滤 {len(tables)} 张表（{'、'.join(dict.fromkeys(tables))}），结果为过滤后数据")
            else:
                parts.append('已按数据权限过滤查询结果')
        if gw.get('hit_sensitive') and gw.get('is_allowed', True):
            parts.append('结果涉及敏感字段，仅返回聚合统计值')

    # 空结果归因：执行成功但 0 行 → 结合权限过滤情况给出可能原因
    if (query_result and not query_result.get('error')
            and query_result.get('row_count') == 0):
        filtered = bool(gw and gw.get('was_modified'))
        if filtered:
            parts.append('查询返回 0 行：数据权限行级过滤后无匹配数据'
                         '（也可能数据本身为空或筛选条件过严）；'
                         '如预期应有数据，请联系管理员确认行级权限范围')
        else:
            parts.append('查询返回 0 行：未匹配到数据，可能筛选条件过严或数据本身为空')
    return '；'.join(parts) if parts else None


def _infer_visible_db_type(user: dict) -> Optional[str]:
    """全库模式：从用户可见的库中推断 db_type（取首个有类型的库）

    供 LLM prompt 的引用符提示使用；执行时仍按 SQL 库前缀精确路由到数据源。
    无可见库或全部无类型时返回 None（沿用请求兜底类型）。
    """
    try:
        from app.permissions import get_visible_schema_ids
        from models.schema import DbSchema
        visible = get_visible_schema_ids(user)
        with session_scope() as db:
            q = db.query(DbSchema.name, DbSchema.db_type)
            if visible is not None:
                if not visible:
                    return None
                q = q.filter(DbSchema.id.in_(visible))
            for _name, dtype in q.all():
                if dtype:
                    return dtype
        return None
    except Exception:
        return None


def _resolve_fallback_schema(user: dict, sql: str) -> Optional[str]:
    """全库模式 SQL 无库前缀时：可见库唯一则直接路由，多库/无库返回 None

    兜底场景：LLM 在全库模式生成 SQL 但漏带库前缀（如 FROM order_detail 而非
    pjmall.order_detail）。仅当用户可见库唯一时才自动补路由，避免多库歧义；
    SQL 自带库前缀时返回 None（执行器按前缀精确路由）。
    """
    from services.sql_executor import _extract_sql_schema_names
    if _extract_sql_schema_names(sql):
        return None
    try:
        from app.permissions import get_visible_schema_ids
        from models.schema import DbSchema
        visible = get_visible_schema_ids(user)
        with session_scope() as db:
            if visible is None:
                # 无权限限制（如 admin）：系统仅 1 个库时才兜底
                names = [n for (n,) in db.query(DbSchema.name).all()]
                return names[0] if len(names) == 1 else None
            if len(visible) != 1:
                return None
            return db.query(DbSchema.name).filter(DbSchema.id == visible[0]).scalar()
    except Exception as e:
        logger.warning(f"[conversation_router] 兜底路由解析失败: {e}")
        return None


def _get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置（api_key 解密后供客户端使用）

    查找顺序：
      1. 指定 config_id（限本人或公共）
      2. 本人默认配置
      3. 公共默认配置（is_public + is_default）——非技术用户无自有配置时
         可用管理员公开的模型，避免「未配置 API 密钥」报错
    """
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
            if config is None:
                # 回退公共默认配置（管理员公开给全员使用的模型）
                config = db.query(LLMConfig).filter(
                    LLMConfig.is_public == True,
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
                # 注意不能用 or 回退：temperature=0.0 是合法值（falsy 会被 0.7 覆盖）
                'max_tokens': config.max_tokens if config.max_tokens is not None else 8000,
                'temperature': config.temperature if config.temperature is not None else 0.0,
                'thinking_mode': config.thinking_mode or 'auto',
                'timeout': config.timeout if config.timeout is not None else 300
            }
        return None


# LLM/网络错误分类关键词（小写匹配）→ 用户可读的失败原因
_LLM_ERROR_PATTERNS = [
    (('timeout', 'timed out', '读超时', '连接超时'), 504,
     '模型响应超时，请稍后重试或更换模型（思考类模型对复杂问题可能超过配置的超时时间）'),
    (('invalid api key', 'unauthorized', '401', 'authentication'), 502,
     '模型 API 密钥无效或未授权，请在模型管理页检查 API Key 配置'),
    (('429', 'too many requests', 'rate limit', '限流', '访问量过大'), 502,
     '模型服务限流/访问量过大，请稍后重试或更换其他模型'),
    (('api密钥未配置', '未配置', 'api密钥'), 400,
     '未配置模型 API 密钥，请先在模型管理页完成配置'),
    (('ssrf', '内网地址', 'scheme 不合法', 'llm api 地址'), 400,
     '模型 API 地址配置不合法，请在模型管理页检查 base_url'),
    (('no such column', 'no such table', 'unknown column', 'doesn\'t exist'), 500,
     '查询引用了不存在的表/字段：可能是模型生成了错误字段名，重试或补充更明确的描述'),
]


def _classify_llm_failure(e: Exception, context: str) -> HTTPException:
    """把生成链路的异常归类为用户可读的失败原因。

    此前统一 500「xx失败: {原始异常}」，用户无法区分是模型问题、网络问题、
    配置问题还是权限/拦截问题。按关键词归到 4 类（超时/认证/限流/配置），
    其余保持 500 但提示排查方向。完整异常始终记入日志。
    """
    logger.error(f"{context}: {e}", exc_info=True)
    msg = str(e) or e.__class__.__name__.lower()
    low = msg.lower()
    for keywords, status, friendly in _LLM_ERROR_PATTERNS:
        if any(k in low for k in keywords):
            return HTTPException(status_code=status, detail=friendly)
    return HTTPException(status_code=500,
                         detail=f"{context}: {msg[:300]}")


def _mark_llm_config_arrears(config_id: Optional[int]) -> None:
    """LLM 厂商返回余额不足/配额暂停时，把该配置状态标记为欠费。

    仅更新 status 一个字段（其余字段与状态不动）；恢复由用户续费后手动改回。
    """
    if not config_id:
        return
    try:
        from models.llm import LLMConfig
        with session_scope() as db:
            db.query(LLMConfig).filter(LLMConfig.id == config_id).update({
                'status': 'arrears', 'updated_at': now_beijing()})
            db.commit()
        logger.warning(f"LLM 配置 {config_id} 厂商返回余额不足，已标记为欠费(arrears)")
    except Exception as e:
        logger.warning(f"标记 LLM 配置欠费状态失败: {e}")


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
            temperature=llm_config['temperature'],
            thinking_mode=llm_config.get('thinking_mode', 'auto')
        )
        # 记录实际使用的配置 ID，供欠费错误回写状态（默认配置回退后仍可定位）
        llm_client.config_id = llm_config['id']
    else:
        llm_client = LLMClient()

    return llm_client


def _llm_info_from_result(llm_client: "LLMClient", result: dict) -> dict:
    """从生成结果组装 llm_info（模型/耗时/Token），供前端消息气泡展示"""
    tokens = result.get('tokens', {}) or {}
    return {
        'provider': getattr(llm_client, 'provider', '') or '',
        'model': getattr(llm_client, 'model', '') or '',
        'duration_ms': result.get('duration_ms', 0) or 0,
        'prompt_tokens': tokens.get('prompt_tokens', 0),
        'completion_tokens': tokens.get('completion_tokens', 0),
        'reasoning_tokens': tokens.get('reasoning_tokens', 0),
        'total_tokens': tokens.get('total_tokens', 0),
    }


def _get_llm_infos_by_call_ids(call_ids: List[int]) -> dict:
    """按 llm_call_id 批量查遥测调用明细，返回 {call_id: llm_info}

    历史消息的模型/耗时/Token 存在遥测库（跨库），此处一次性取回避免 N+1。
    """
    ids = [cid for cid in call_ids if cid]
    if not ids:
        return {}
    from models.llm import LLMCall
    try:
        with session_scope(telemetry=True) as db:
            rows = db.query(LLMCall).filter(LLMCall.id.in_(ids)).all()
            return {
                r.id: {
                    'provider': r.provider or '',
                    'model': r.model or '',
                    'duration_ms': r.duration_ms or 0,
                    'prompt_tokens': r.prompt_tokens or 0,
                    'completion_tokens': r.completion_tokens or 0,
                    'reasoning_tokens': r.reasoning_tokens or 0,
                    'total_tokens': r.total_tokens or 0,
                } for r in rows
            }
    except Exception as e:
        logger.warning(f"[conversation_router] 查询遥测调用明细失败: {e}")
        return {}


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


def _resolve_knowledge_ids(knowledge_ids: Optional[List[int]] = None,
                           knowledge_id: Optional[int] = None) -> List[int]:
    """归一化知识库选择：优先 knowledge_ids（多选），兼容 knowledge_id（旧版单条）"""
    if knowledge_ids:
        return [int(i) for i in knowledge_ids if i]
    if knowledge_id:
        return [int(knowledge_id)]
    return []


def _get_knowledge_safe(user_id: int, knowledge_id: Optional[int] = None,
                        knowledge_ids: Optional[List[int]] = None,
                        exclude_ids: Optional[List[int]] = None) -> str:
    """获取知识内容（支持多条拼接，安全版本，失败返回空字符串）

    exclude_ids: 已由常驻段注入的条目 id，跳过以防同一知识双重注入
    """
    ids = _resolve_knowledge_ids(knowledge_ids, knowledge_id)
    if exclude_ids:
        exclude = {int(i) for i in exclude_ids}
        ids = [i for i in ids if i not in exclude]
    if not ids:
        return ""
    try:
        from app.routers.knowledge_router import get_knowledge_safe
        parts = []
        seen: set = set()
        for kid in ids:
            knowledge = get_knowledge_safe(user_id, kid)
            content = knowledge.get("content", "") if knowledge else ""
            if content and content not in seen:   # 内容级去重，防同一条知识重复注入 prompt
                seen.add(content)
                parts.append(content)
        return "\n\n".join(parts)
    except Exception:
        return ""


# 全局常驻注入预算（字符）：单条 2000 / 总量 6000，超出截断并记 WARNING
_GLOBAL_RULE_ITEM_BUDGET = 2000
_GLOBAL_RULE_TOTAL_BUDGET = 6000


def _get_global_rules_content() -> tuple:
    """全局常驻知识内容（管理员 pin 的 global 条目，人人遵守）。

    Returns:
        (text, pinned_count)：text 为拼好的多段内容（不含【全局规则】标题），
        空字符串表示无常驻条目。
    """
    try:
        from crud.knowledge import knowledge_crud
        items = knowledge_crud.list_global_pinned()
        if not items:
            return "", 0
        parts, total = [], 0
        for it in items:
            d = knowledge_crud.to_dict(it)
            content = (d.get('content') or '').strip()
            if not content:
                continue
            if len(content) > _GLOBAL_RULE_ITEM_BUDGET:
                content = content[:_GLOBAL_RULE_ITEM_BUDGET] + '…(截断)'
            # 首条保底；后续条目超总量预算即止
            if parts and total + len(content) > _GLOBAL_RULE_TOTAL_BUDGET:
                logger.warning(
                    f"全局常驻知识超预算 {total + len(content)}>"
                    f"{_GLOBAL_RULE_TOTAL_BUDGET}，仅注入前 {len(parts)} 条")
                break
            title = d.get('title') or f"知识#{d['id']}"
            parts.append(f"◆ {title}\n{content}")
            total += len(content)
        return "\n\n".join(parts), len(parts)
    except Exception as e:
        logger.warning(f"加载全局常驻知识失败（忽略）: {e}")
        return "", 0


def _get_user_default_knowledge_ids(user_id: int) -> List[int]:
    """旧版默认勾选回退（仅显式不传 knowledge_ids 的 API 调用会走到）。

    我的常驻（pinned_knowledge_ids）已无条件注入，此处排除防双重注入。
    """
    try:
        from app.routers.user_router import _get_pref_ids
        pinned = set(_get_pref_ids(user_id, 'pinned_knowledge_ids'))
        return [i for i in _get_pref_ids(user_id, 'default_knowledge_ids')
                if i not in pinned]
    except Exception:
        return []


def _get_user_pinned_content(user_id: int, global_text: str = '') -> tuple:
    """用户自选常驻知识（每人自己勾选，仅注入本人对话）。

    Args:
        user_id: 用户 id
        global_text: 管理员全局常驻内容，用于内容级去重（同条目不重复注入）

    Returns:
        (text, n, ids)：text 为拼好的多段内容（不含段标题），ids 为实际注入的条目 id
        （供「用户勾选」段排除，防双重注入）；空字符串表示无自选常驻。
    """
    try:
        from app.routers.user_router import _get_pref_ids
        from app.routers.knowledge_router import get_knowledge_safe
        ids = _get_pref_ids(user_id, 'pinned_knowledge_ids')
        if not ids:
            return "", 0, []
        parts, total, seen, effective = [], 0, set(), []
        for kid in ids[:20]:
            k = get_knowledge_safe(user_id, kid)   # 内含可见性校验，越权返回 {}
            content = (k.get('content') or '').strip()
            if not content or content in seen:
                continue
            if global_text and content in global_text:
                continue   # 与管理员全局常驻重复，跳过
            if len(content) > _GLOBAL_RULE_ITEM_BUDGET:
                content = content[:_GLOBAL_RULE_ITEM_BUDGET] + '…(截断)'
            if parts and total + len(content) > _GLOBAL_RULE_TOTAL_BUDGET:
                logger.warning(
                    f"用户自选常驻知识超预算 user={user_id} "
                    f"{total + len(content)}>{_GLOBAL_RULE_TOTAL_BUDGET}，仅注入前 {len(parts)} 条")
                break
            seen.add(content)
            effective.append(kid)
            title = k.get('title') or f"知识#{kid}"
            parts.append(f"◆ {title}\n{content}")
            total += len(content)
        return "\n\n".join(parts), len(parts), effective
    except Exception as e:
        logger.warning(f"加载用户自选常驻知识失败（忽略）: {e}")
        return "", 0, []


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
        reasoning_tokens=tokens.get('reasoning_tokens', 0),
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
@limiter.limit(LIMIT_HEAVY)
def create_conversation(
    request: Request,
    payload: CreateConversationRequest,
    user: CurrentUser
):
    """创建新对话 + 首轮 SQL 生成（重接口：含 LLM 生成）

    注意：body 参数命名为 payload，request 名留给 slowapi 定位 Request。
    """
    user_id = user['user_id']

    # 链路追踪：前置步骤（模型/知识库）— StepTrace 统一结构（docs §5.2）
    # 鉴权（AUTH_SCHEMA_CHECK）移至链路表聚合之后：召回确定本次涉及的库/表再校验
    from core.gen_audit import StepTracker
    pre_tracker = StepTracker()
    pre_log = []

    # 数据库类型：选了库则以库类型为准；全库模式（None）从可见库推断（供 LLM 引用符提示）
    db_type = payload.db_type
    if payload.schema_name:
        with session_scope() as db_cfg:
            db_type = schema_service.get_schema_type_by_name(
                db_cfg, payload.schema_name) or db_type
    else:
        inferred = _infer_visible_db_type(user)
        if inferred:
            db_type = inferred

    try:
        llm_client = _build_llm_client(user_id, payload.llm_config_id)
        # 知识库支持多选（knowledge_ids 优先，兼容旧版 knowledge_id）；
        # 未显式选择时回退用户默认勾选（显式传 [] 表示强制不带）
        knowledge_ids = _resolve_knowledge_ids(payload.knowledge_ids, payload.knowledge_id)
        used_default_kb = False
        if not knowledge_ids and payload.knowledge_ids is None and payload.knowledge_id is None:
            knowledge_ids = _get_user_default_knowledge_ids(user_id)
            used_default_kb = bool(knowledge_ids)
        # 常驻知识 = 管理员全局常驻（人人遵守）+ 用户自选常驻（仅本人）+ 用户勾选知识
        # 自选常驻条目从勾选段排除，防同一知识双重注入
        global_text, pinned_n = _get_global_rules_content()
        user_pinned_text, user_pinned_n, user_pinned_ids = _get_user_pinned_content(user_id, global_text)
        selected_content = _get_knowledge_safe(user_id, knowledge_ids=knowledge_ids,
                                               exclude_ids=user_pinned_ids)
        kb_sections = []
        if global_text:
            kb_sections.append(f"【全局规则（管理员发布，人人遵守）】\n{global_text}")
        if user_pinned_text:
            kb_sections.append(f"【我的常驻知识（自行勾选，仅本人生效）】\n{user_pinned_text}")
        if selected_content:
            kb_sections.append(f"【领域知识（用户勾选）】\n{selected_content}")
        knowledge_content = "\n\n".join(kb_sections)

        pre_tracker.add(pre_log, "LLM_CONFIG_LOAD", data={
            "provider": getattr(llm_client, 'provider', '') or 'default',
            "model": getattr(llm_client, 'model', '') or 'default',
            "config_id": payload.llm_config_id},
            summary=f"模型 {getattr(llm_client, 'model', '') or 'default'}")
        pre_tracker.add(pre_log, "KNOWLEDGE_LOAD", data={
            "knowledge_ids": knowledge_ids,
            "user_selected": bool(payload.knowledge_ids or payload.knowledge_id),
            "used_default_kb": used_default_kb,
            "global_pinned": pinned_n,
            "user_pinned": user_pinned_n,
            "note": "用户显式选择的知识库；链路「知识召回」步为自动概念召回(与勾选无关)" if not knowledge_ids else "",
            "loaded": bool(knowledge_content),
            "content_length": len(knowledge_content)},
            summary=(f"全局常驻 {pinned_n} · 我的常驻 {user_pinned_n} · "
                     f"勾选 {len(knowledge_ids or [])} 条"))

        session = ChatSession(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator,
            user=user
        )

        # 第一轮：走完整流水线（库不可见时流水线抛 SchemaAuthError → 403）
        result = session.process_first_message(
            query=payload.query,
            schema_name=payload.schema_name,
            db_type=db_type,
            knowledge_content=knowledge_content,
            pre_log=pre_log,
        )

        # 执行生成的 SQL：校验失败（含权限拦截）或信息不足时不执行，前端展示原因
        if result.get('need_more_info') or not result.get('is_valid'):
            query_result = None
        else:
            exec_schema = payload.schema_name or _resolve_fallback_schema(
                user, result.get('sql', ''))
            query_result = _execute_generated_sql(
                result.get('sql', ''), exec_schema, db_type)

        # 保存到数据库
        import time as _time
        _persist_t0 = _time.time()
        with session_scope() as db:
            title = payload.query[:80] + ("..." if len(payload.query) > 80 else "")

            schema_id = schema_service.get_schema_id_by_name(db, payload.schema_name)

            conversation = Conversation(
                user_id=user_id,
                title=title,
                schema_id=schema_id,
                db_type=db_type,
                llm_config_id=payload.llm_config_id,
                knowledge_id=knowledge_ids[0] if knowledge_ids else payload.knowledge_id,
                knowledge_ids=json.dumps(knowledge_ids, ensure_ascii=False) if knowledge_ids else None,
                schema_tables=json.dumps(result.get('tables') or [], ensure_ascii=False)
            )
            db.add(conversation)
            db.flush()

            # 用户消息
            user_msg = ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=payload.query
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
                result_data=json.dumps(query_result, ensure_ascii=False) if query_result else None,
                permission_note=_permission_note(result, query_result)
            )
            db.add(assistant_msg)
            db.flush()

            # flush 后 id 已分配，先取回再 commit（避免 commit expire 后属性刷新异常）
            conversation_id = cast(int, conversation.id)
            assistant_msg_id = cast(int, assistant_msg.id)
            db.commit()
        # 保存 LLM 调用记录（遥测库）+ 回填关联键（主库）
        # 条件留痕：记录实际路由的库与数据源类型（全库模式下区别于请求参数 None/sqlite 兜底值）
        cond_schema = ((query_result or {}).get('schema')
                       or payload.schema_name or '全库')
        cond_db = ((query_result or {}).get('datasource_type') or db_type or 'unknown')
        call_id = _record_telemetry(
            user_id, llm_client, payload.query,
            conditions=f"schema={cond_schema}, db_type={cond_db}",
            result=result, conversation_id=conversation_id,
            config_id=payload.llm_config_id)

        prompt_text = (result.get('messages') or [{}])[0].get('content')
        prompt_id = telemetry.get_or_create_prompt(prompt_text) if prompt_text else None

        if call_id or prompt_id:
            conversation_crud.bind_telemetry(conversation_id, assistant_msg_id, call_id, prompt_id)
        logger.info(f"对话创建成功: id={conversation_id}, user_id={user_id}")

        # 后置步骤：SQL 执行 + 消息持久化（追加到 pipeline_log，回写审计）
        # StepTrace 统一结构（docs §5.2）：PREFIX_REPAIR / SQL_EXECUTE / MESSAGE_PERSIST
        pipeline_log = result.get('pipeline_log') or []
        post_tracker = StepTracker()
        _pr = (query_result or {}).get('prefix_repair')
        if _pr is not None:
            post_tracker.add(pipeline_log, "PREFIX_REPAIR", data=_pr,
                             status='ok' if _pr.get('repaired') else 'skip',
                             error=_pr.get('error'),
                             summary=('补前缀: ' + '; '.join(_pr.get('repaired') or []))
                             if _pr.get('repaired') else
                             ('解析失败，跳过补前缀' if _pr.get('error') else '无需补前缀'))
        _exec_error = (query_result or {}).get('error', '') or None
        _executed = bool(query_result) and not _exec_error
        if query_result is None:
            _exec_status = 'skip'
        elif _exec_error:
            _exec_status = 'error'
        else:
            _exec_status = 'ok'
        post_tracker.add(pipeline_log, "SQL_EXECUTE", data={
            "executed": _executed,
            "row_count": (query_result or {}).get('row_count', 0),
            "schema": (query_result or {}).get('schema'),
            "datasource_type": (query_result or {}).get('datasource_type'),
            "error": _exec_error},
            status=_exec_status,
            error=_exec_error if _exec_status != 'skip' else '未执行：生成被拦截或 SQL 校验未通过',
            summary=(f"执行 {('成功' if _executed else '失败')} · "
                     f"{(query_result or {}).get('row_count', 0)} 行 · "
                     f"库 {(query_result or {}).get('schema') or '-'}"
                     f"({(query_result or {}).get('datasource_type') or '-'})")
            if query_result is not None else "未执行",
            duration_ms=(query_result or {}).get('duration_ms'))
        post_tracker.add(pipeline_log, "MESSAGE_PERSIST", data={
            "conversation_id": conversation_id, "assistant_msg_id": assistant_msg_id,
            "telemetry_call_id": call_id, "prompt_id": prompt_id},
            status='ok', summary="消息与遥测已落库",
            duration_ms=int((_time.time() - _persist_t0) * 1000))
        from core.gen_audit import update_pipeline_log
        update_pipeline_log(result.get('audit_log_id'),
                            json.dumps(pipeline_log, ensure_ascii=False, default=str))

        return {
            "conversation": {
                "id": conversation_id,
                "title": title,
                "schema_name": payload.schema_name,
                "db_type": payload.db_type
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
                "llm_info": _llm_info_from_result(llm_client, result),
                "query_result": query_result,
                "need_more_info": result.get('need_more_info', False),
                "missing_info": result.get('missing_info'),
                "suggestion": result.get('suggestion'),
                "permission_note": _permission_note(result, query_result),
            }
        }

    except HTTPException:
        raise
    except LLMArrearsError as e:
        # 厂商返回余额不足/配额暂停：标记配置状态为欠费（仅此字段，其余不动）
        _mark_llm_config_arrears(getattr(llm_client, 'config_id', None))
        logger.error(f"创建对话失败(模型欠费): {e}")
        raise HTTPException(status_code=502,
                            detail="模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复")
    except SchemaAuthError as e:
        # 库级鉴权拦截（链路表聚合后的 AUTH_SCHEMA_CHECK 步）：不建会话、不落消息
        logger.warning(f"创建对话被鉴权拦截: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise _classify_llm_failure(e, f"创建对话失败")


@router.post("/{conversation_id}/messages")
@limiter.limit(LIMIT_HEAVY)
def send_message(
    conversation_id: int,
    request: Request,
    payload: SendMessageRequest,
    user: CurrentUser
):
    """发送跟进消息 + 生成修正 SQL

    注意：body 参数命名为 payload（不能用 request），request 名须留给
    Starlette Request 供 slowapi 限流按参数名查找。
    """
    user_id = user['user_id']

    try:
        with session_scope() as db:
            # 验证对话归属（admin 与列表权限一致，可访问全部对话）
            q = db.query(Conversation).filter(Conversation.id == conversation_id)
            if user.get('role') != 'admin':
                q = q.filter(Conversation.user_id == user_id)
            conversation = q.first()
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
            # 已存的多选知识库（JSON 数组），旧对话为空则回退单条 knowledge_id
            conv_knowledge_ids = []
            if conversation.knowledge_ids:
                try:
                    conv_knowledge_ids = json.loads(conversation.knowledge_ids) or []
                except (json.JSONDecodeError, TypeError):
                    conv_knowledge_ids = []
            if not conv_knowledge_ids and conv_knowledge_id:
                conv_knowledge_ids = [conv_knowledge_id]
            # 在 session 关闭前取出首轮表集合（避免退出 with 后 detached 访问报错）
            conv_schema_tables = conversation.schema_tables

        # ── 对话中切换模型 / 知识库 ──
        # 请求显式传值 → 本次生效并持久化到会话（后续轮次沿用）；不传 → 沿用会话已存配置
        if payload.llm_config_id is not None:
            conv_llm_config_id = payload.llm_config_id
        if payload.knowledge_ids is not None or payload.knowledge_id is not None:
            conv_knowledge_ids = _resolve_knowledge_ids(
                payload.knowledge_ids, payload.knowledge_id)
            conv_knowledge_id = conv_knowledge_ids[0] if conv_knowledge_ids else None
        if (payload.llm_config_id is not None
                or payload.knowledge_ids is not None
                or payload.knowledge_id is not None):
            with session_scope() as db_upd:
                db_upd.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).update({
                    'llm_config_id': conv_llm_config_id,
                    'knowledge_id': conv_knowledge_id,
                    'knowledge_ids': (json.dumps(conv_knowledge_ids, ensure_ascii=False)
                                      if conv_knowledge_ids else None),
                    'updated_at': now_beijing(),
                })
                db_upd.commit()
            logger.info(
                f"对话 {conversation_id} 配置切换: "
                f"llm_config_id={conv_llm_config_id}, knowledge_ids={conv_knowledge_ids}")

        # 从三层模型重建 schema CSV（fallback 全量，用于未记录首轮表集合的旧对话；
        # 权限裁剪在 SchemaRetriever.get_field_rows 内完成——编排层构建权限快照传入）
        from core.recall_scope import build_recall_scope
        schema_csv = SchemaRetriever(user=user).build_full_schema_csv(
            schema_name, scope=build_recall_scope(user))
        # 首轮召回表集合（新对话已记录；旧对话为空则追问轮沿用全量 schema_csv）
        first_tables: list = []
        if conv_schema_tables:
            try:
                first_tables = json.loads(conv_schema_tables) or []
            except (json.JSONDecodeError, TypeError):
                first_tables = []

        llm_client = _build_llm_client(user_id, conv_llm_config_id)

        # 链路追踪：前置步骤（模型/知识库）— StepTrace 统一结构（docs §5.2）
        # 鉴权（AUTH_SCHEMA_CHECK）移至链路表聚合之后：召回确定本次涉及的库/表再校验
        from core.gen_audit import StepTracker
        pre_tracker = StepTracker()
        pre_log = []
        pre_tracker.add(pre_log, "LLM_CONFIG_LOAD", data={
            "provider": getattr(llm_client, 'provider', '') or 'default',
            "model": getattr(llm_client, 'model', '') or 'default',
            "config_id": conv_llm_config_id},
            summary=f"模型 {getattr(llm_client, 'model', '') or 'default'}")
        # 跟进消息的知识内容需在日志步骤前加载（避免引用未赋值变量）；
        # 常驻知识（管理员全局 + 用户自选）每次追问都注入，自选常驻条目从勾选段排除
        global_text, pinned_n = _get_global_rules_content()
        user_pinned_text, user_pinned_n, user_pinned_ids = _get_user_pinned_content(user_id, global_text)
        selected_content = _get_knowledge_safe(
            user_id, knowledge_ids=conv_knowledge_ids, exclude_ids=user_pinned_ids)
        kb_sections = []
        if global_text:
            kb_sections.append(f"【全局规则（管理员发布，人人遵守）】\n{global_text}")
        if user_pinned_text:
            kb_sections.append(f"【我的常驻知识（自行勾选，仅本人生效）】\n{user_pinned_text}")
        if selected_content:
            kb_sections.append(f"【领域知识（用户勾选）】\n{selected_content}")
        knowledge_content = "\n\n".join(kb_sections)
        pre_tracker.add(pre_log, "KNOWLEDGE_LOAD", data={
            "knowledge_ids": conv_knowledge_ids,
            "user_selected": bool(conv_knowledge_ids),
            "global_pinned": pinned_n,
            "user_pinned": user_pinned_n,
            "note": "用户显式选择的知识库；链路「知识召回」步为自动概念召回(与勾选无关)" if not conv_knowledge_ids else "",
            "loaded": bool(knowledge_content),
            "content_length": len(knowledge_content)},
            summary=(f"全局常驻 {pinned_n} · 我的常驻 {user_pinned_n} · "
                     f"勾选 {len(conv_knowledge_ids or [])} 条"))

        session = ChatSession(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator,
            user=user
        )

        # 跟进消息（库不可见时流水线抛 SchemaAuthError → 403）
        result = session.process_followup_message(
            conversation_messages=history,
            new_user_content=payload.content,
            schema_csv=schema_csv,
            first_tables=first_tables,
            db_type=conv_db_type,
            schema_name=schema_name,
            knowledge_content=knowledge_content,
            pre_log=pre_log,
        )

        # 执行生成的 SQL：校验失败（含权限拦截）或信息不足时不执行，前端展示原因
        if result.get('need_more_info') or not result.get('is_valid'):
            query_result = None
        else:
            exec_schema = schema_name or _resolve_fallback_schema(
                user, result.get('sql', ''))
            query_result = _execute_generated_sql(
                result.get('sql', ''), exec_schema, conv_db_type)

        # 保存消息
        import time as _time
        _persist_t0 = _time.time()
        with session_scope() as db:
            user_msg = ConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content=payload.content
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
                result_data=json.dumps(query_result, ensure_ascii=False) if query_result else None,
                permission_note=_permission_note(result, query_result)
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
        # 条件留痕：追问轮同样记录实际路由的库与数据源类型
        cond_schema = ((query_result or {}).get('schema')
                       or schema_name or '全库')
        cond_db = ((query_result or {}).get('datasource_type') or conv_db_type or 'unknown')
        call_id = _record_telemetry(
            user_id, llm_client, payload.content,
            conditions=(f"conversation={conversation_id}, followup, "
                        f"schema={cond_schema}, db_type={cond_db}"),
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

        # 后置步骤：SQL 执行 + 消息持久化（追加到 pipeline_log，回写审计）
        # StepTrace 统一结构（docs §5.2）：PREFIX_REPAIR / SQL_EXECUTE / MESSAGE_PERSIST
        pipeline_log = result.get('pipeline_log') or []
        post_tracker = StepTracker()
        _pr = (query_result or {}).get('prefix_repair')
        if _pr is not None:
            post_tracker.add(pipeline_log, "PREFIX_REPAIR", data=_pr,
                             status='ok' if _pr.get('repaired') else 'skip',
                             error=_pr.get('error'),
                             summary=('补前缀: ' + '; '.join(_pr.get('repaired') or []))
                             if _pr.get('repaired') else
                             ('解析失败，跳过补前缀' if _pr.get('error') else '无需补前缀'))
        _exec_error = (query_result or {}).get('error', '') or None
        _executed = bool(query_result) and not _exec_error
        if query_result is None:
            _exec_status = 'skip'
        elif _exec_error:
            _exec_status = 'error'
        else:
            _exec_status = 'ok'
        post_tracker.add(pipeline_log, "SQL_EXECUTE", data={
            "executed": _executed,
            "row_count": (query_result or {}).get('row_count', 0),
            "schema": (query_result or {}).get('schema'),
            "datasource_type": (query_result or {}).get('datasource_type'),
            "error": _exec_error},
            status=_exec_status,
            error=_exec_error if _exec_status != 'skip' else '未执行：生成被拦截或 SQL 校验未通过',
            summary=(f"执行 {('成功' if _executed else '失败')} · "
                     f"{(query_result or {}).get('row_count', 0)} 行 · "
                     f"库 {(query_result or {}).get('schema') or '-'}"
                     f"({(query_result or {}).get('datasource_type') or '-'})")
            if query_result is not None else "未执行",
            duration_ms=(query_result or {}).get('duration_ms'))
        post_tracker.add(pipeline_log, "MESSAGE_PERSIST", data={
            "conversation_id": conversation_id,
            "user_msg_id": user_msg_id, "assistant_msg_id": assistant_msg_id,
            "telemetry_call_id": call_id},
            status='ok', summary="消息与遥测已落库",
            duration_ms=int((_time.time() - _persist_t0) * 1000))
        from core.gen_audit import update_pipeline_log
        update_pipeline_log(result.get('audit_log_id'),
                            json.dumps(pipeline_log, ensure_ascii=False, default=str))

        return {
            "user_message": {
                "id": user_msg_id,
                "role": "user",
                "content": payload.content
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
                "llm_info": _llm_info_from_result(llm_client, result),
                "query_result": query_result,
                "need_more_info": result.get('need_more_info', False),
                "missing_info": result.get('missing_info'),
                "suggestion": result.get('suggestion'),
                "permission_note": _permission_note(result, query_result),
            }
        }

    except HTTPException:
        raise
    except LLMArrearsError as e:
        # 厂商返回余额不足/配额暂停：标记配置状态为欠费（仅此字段，其余不动）
        _mark_llm_config_arrears(getattr(llm_client, 'config_id', None))
        logger.error(f"发送消息失败(模型欠费): {e}")
        raise HTTPException(status_code=502,
                            detail="模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复")
    except SchemaAuthError as e:
        # 库级鉴权拦截（链路表聚合后的 AUTH_SCHEMA_CHECK 步）：不落消息、不执行
        logger.warning(f"发送消息被鉴权拦截: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise _classify_llm_failure(e, f"发送消息失败")


@router.get("")
@limiter.limit(LIMIT_READ)
def list_conversations(
    request: Request,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=200),
):
    """获取对话列表（分页，按更新时间倒序）。管理员看全部，用户看自己。

    Args:
        limit: 每页条数（默认 20，最大 200）
        offset: 偏移量（分页游标）
        search: 关键字，匹配标题或会话内任意消息内容（空则不过滤）

    Returns:
        {"items": [...], "total": 总条数}
    """
    user_id = user['user_id']
    is_admin = user.get('role') == 'admin'

    conversations, total = conversation_crud.list_paged(
        user_id, is_admin, limit=limit, offset=offset,
        search=(search or '').strip() or None)
    # schema id → name 映射（一次查询）
    schema_names = schema_crud.name_map()
    # 各对话消息数（一次 GROUP BY 聚合，避免 N+1 count）
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

    return ok({"items": result, "total": total})
@router.get("/{conversation_id}/messages")
@limiter.limit(LIMIT_READ)
def get_messages(
    conversation_id: int,
    request: Request,
    user: CurrentUser
):
    """获取对话消息历史"""
    user_id = user['user_id']

    with session_scope() as db:
        # admin 与列表权限一致，可查看全部对话的消息
        q = db.query(Conversation).filter(Conversation.id == conversation_id)
        if user.get('role') != 'admin':
            q = q.filter(Conversation.user_id == user_id)
        conversation = q.first()
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).order_by(ConversationMessage.created_at.asc()).all()

        # 批量取回 assistant 消息关联的遥测明细（模型/耗时/Token）
        call_map = _get_llm_infos_by_call_ids(
            [m.llm_call_id for m in messages if m.role == 'assistant'])

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
                llm_info=call_map.get(msg.llm_call_id) if msg.role == 'assistant' else None,
                permission_note=msg.permission_note,
                created_at=msg.created_at.isoformat() if msg.created_at else ""
            )
            for msg in messages
        ]
@router.delete("/{conversation_id}")
@limiter.limit(LIMIT_WRITE)
def delete_conversation(
    conversation_id: int,
    request: Request,
    user: CurrentUser
):
    """删除对话"""
    user_id = user['user_id']

    with session_scope() as db:
        # admin 与列表权限一致，可删除全部对话
        q = db.query(Conversation).filter(Conversation.id == conversation_id)
        if user.get('role') != 'admin':
            q = q.filter(Conversation.user_id == user_id)
        conversation = q.first()
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")
    
        # 删除关联消息
        db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation_id
        ).delete()
    
        db.delete(conversation)
        db.commit()
    
        return ok_msg("对话已删除")
# ── Internal helpers ──────────────────────────────────────────────
# （schema CSV 全量重建已下沉 SchemaRetriever.build_full_schema_csv——
#   权限裁剪属于召回层职责，路由层不再自行拼权限原语）
