# -*- coding: UTF-8 -*-
"""
知识库路由 — 领域知识管理（业务口径/表关系/计算规则等，生成 SQL 时注入提示词）

数据层：models/knowledge.py 的 KnowledgeItem（typed 结构化：knowledge_type/aliases/payload/scope_schema_id）
API 契约：前端通过 /api/knowledge 访问；字段召回增强端点 /api/knowledge/recall。
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from app.auth import CurrentUser
from app.limiter import LIMIT_HEAVY, LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit, logger
from app.permissions import get_visible_knowledge_ids, is_admin
from crud.base import session_scope
from crud.knowledge import knowledge_crud
from models.knowledge import KnowledgeItem
from models.user import User

router = APIRouter()


# 内置知识类型（平台不解释具体值，仅做下拉/渲染路由）
KNOWLEDGE_TYPES = [
    'note',            # 普通笔记 / 自由文本
    'terminology',     # 术语别名
    'calculation',     # 计算规则
    'relation',        # 表关系
    'value_domain',    # 取值域
    'convention',      # 约定
    'entity_map',      # 实体映射
    'sample_qa',       # 样例问答
]


class KnowledgeRequest(BaseModel):
    """知识库条目请求（typed 结构化）

    部分更新：用 Pydantic v2 的 model_fields_set 判断字段是否被显式传入，
    未传入的字段不写入，避免覆盖其余字段。
    """
    title: Optional[str] = None
    content: Optional[str] = None
    knowledge_type: Optional[str] = None
    aliases: Optional[List[str]] = None
    payload: Optional[Dict[str, Any]] = None
    scope_schema_id: Optional[int] = None

    @field_validator('title')
    @classmethod
    def validate_title(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError('标题长度不能超过200个字符')
        return v

    @field_validator('content')
    @classmethod
    def validate_content(cls, v):
        if v is not None and len(v) > 5000:
            raise ValueError('知识内容长度不能超过5000个字符')
        return v

    @field_validator('knowledge_type')
    @classmethod
    def validate_type(cls, v):
        if v is not None and v not in KNOWLEDGE_TYPES:
            raise ValueError(f'不支持的知识类型: {v}')
        return v


class KnowledgeResponse(BaseModel):
    """知识库条目响应"""
    id: int
    user_id: int
    title: Optional[str]
    content: Optional[str]
    knowledge_type: str = 'note'
    aliases: List[str] = []
    payload: Dict[str, Any] = {}
    scope_schema_id: Optional[int] = None
    is_active: int
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class KnowledgeListResponse(BaseModel):
    """知识库列表响应"""
    items: List[KnowledgeResponse]
    total: int


class KnowledgeRecallRequest(BaseModel):
    """知识条目单独召回请求"""
    query: str
    scope_schema_id: Optional[int] = None


class KnowledgeRecallResponse(BaseModel):
    """知识条目单独召回响应"""
    items: List[Dict[str, Any]]
    prompt_text: str
    related_tables: List[str]


def _to_dict(item: KnowledgeItem) -> dict:
    return knowledge_crud.to_dict(item)


def get_all_knowledge(user: dict, limit: int = 20, offset: int = 0) -> tuple:
    """获取知识库条目（按用户权限过滤）"""
    with session_scope() as db:
        query = db.query(KnowledgeItem).filter(KnowledgeItem.is_active == 1)
        visible_ids = get_visible_knowledge_ids(user)
        if visible_ids is not None:
            if not visible_ids:
                return [], 0
            query = query.filter(KnowledgeItem.id.in_(visible_ids))
        total = query.count()
        items = query.order_by(KnowledgeItem.updated_at.desc()).limit(limit).offset(offset).all()
        # 必须在会话关闭前 expunge，否则 session.close() 会过期属性，
        # 会话外访问 item.id 触发惰性刷新 → DetachedInstanceError
        for obj in items:
            db.expunge(obj)
        return items, total


def get_knowledge_safe(user_id: int, knowledge_id: int = None) -> dict:
    """安全获取知识条目（含用户授权校验，防越权读取）"""
    if not knowledge_id:
        return {}
    if not isinstance(knowledge_id, int) or knowledge_id <= 0:
        return {}
    with session_scope() as db:
        item = db.query(KnowledgeItem).filter(
            KnowledgeItem.id == knowledge_id,
            KnowledgeItem.is_active == 1
        ).first()
        if not item:
            return {}
        from models.role import Role, UserRole
        usr = db.query(User).filter(User.id == user_id).first()
        roles = [row[0] for row in db.query(Role.code).join(
            UserRole, UserRole.role_id == Role.id).filter(UserRole.user_id == user_id).all()]
        if not (usr and is_admin({'user_id': user_id, 'role': usr.role, 'roles': roles})):
            visible_ids = get_visible_knowledge_ids({
                'user_id': user_id, 'role': usr.role if usr else 'user', 'roles': roles})
            if visible_ids is not None and knowledge_id not in visible_ids:
                return {}
        return {
            'id': item.id,
            'title': item.title,
            'content': item.content or ''
        }
@router.get("", response_model=KnowledgeListResponse)
@limiter.limit(LIMIT_READ)
def list_knowledge(
    request: Request,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """获取知识库列表"""
    items, total = get_all_knowledge(user, limit, offset)
    return {'items': [_to_dict(item) for item in items], 'total': total}


@router.post("", response_model=KnowledgeResponse)
@limiter.limit(LIMIT_WRITE)
def create_knowledge(
    request: Request,
    data: KnowledgeRequest,
    user: CurrentUser
):
    """创建知识条目"""
    try:
        item = knowledge_crud.create(
            user_id=user['user_id'],
            title=data.title,
            content=data.content or '',
            knowledge_type=data.knowledge_type or 'note',
            aliases=json.dumps(data.aliases or [], ensure_ascii=False),
            payload=json.dumps(data.payload or {}, ensure_ascii=False),
            scope_schema_id=data.scope_schema_id,
        )
        log_audit(user, "create_knowledge", f"title={data.title} type={data.knowledge_type}")
        return _to_dict(item)
    except Exception as e:
        logger.error(f"创建知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
@limiter.limit(LIMIT_READ)
def get_knowledge(
    request: Request,
    knowledge_id: int,
    user: CurrentUser
):
    """获取单条知识（权限过滤）"""
    try:
        visible_ids = get_visible_knowledge_ids(user)
        if visible_ids is not None and knowledge_id not in visible_ids:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")

        item = knowledge_crud.get_one(id=knowledge_id, is_active=1)
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")

        return _to_dict(item)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{knowledge_id}", response_model=KnowledgeResponse)
@limiter.limit(LIMIT_WRITE)
def update_knowledge(
    request: Request,
    knowledge_id: int,
    data: KnowledgeRequest,
    user: CurrentUser
):
    """更新知识（所有者或管理员）"""
    try:
        item = knowledge_crud.get_by_id(knowledge_id)
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能修改自己创建的知识")

        update_fields = {}
        provided = data.model_fields_set
        if 'title' in provided:
            update_fields['title'] = data.title
        if 'content' in provided:
            update_fields['content'] = data.content
        if 'knowledge_type' in provided:
            update_fields['knowledge_type'] = data.knowledge_type
        if 'aliases' in provided:
            update_fields['aliases'] = json.dumps(data.aliases or [], ensure_ascii=False)
        if 'payload' in provided:
            update_fields['payload'] = json.dumps(data.payload or {}, ensure_ascii=False)
        if 'scope_schema_id' in provided:
            update_fields['scope_schema_id'] = data.scope_schema_id

        knowledge_crud.update(knowledge_id, **update_fields)
        log_audit(user, "update_knowledge", f"id={knowledge_id}")
        return _to_dict(knowledge_crud.get_by_id(knowledge_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{knowledge_id}")
@limiter.limit(LIMIT_WRITE)
def delete_knowledge(
    request: Request,
    knowledge_id: int,
    user: CurrentUser
):
    """删除知识（软删除，所有者或管理员）"""
    try:
        item = knowledge_crud.get_by_id(knowledge_id)
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能删除自己创建的知识")

        knowledge_crud.update(knowledge_id, is_active=0)
        log_audit(user, "delete_knowledge", f"id={knowledge_id}")
        return {"message": "知识已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recall", response_model=KnowledgeRecallResponse)
@limiter.limit(LIMIT_HEAVY)
def recall_knowledge_endpoint(
    request: Request,
    body: KnowledgeRecallRequest,
    user: CurrentUser
):
    """知识条目单独召回：按 query 关键词召回 typed 知识，返回注入提示词的文本块与关联表（用于动态扩表）"""
    try:
        from core.ret_retriever import SchemaRetriever
        retriever = SchemaRetriever(user=user, user_id=user['user_id'])
        result = retriever.recall_knowledge(
            query=body.query,
            scope_schema_id=body.scope_schema_id,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"知识召回失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
