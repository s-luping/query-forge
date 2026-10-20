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
    'terminology',     # 术语别名（L1 业务术语）
    'calculation',     # 计算规则（L2 字段口径）
    'relation',        # 表关系（L4 关联链路）
    'value_domain',    # 取值域（L2 字段口径）
    'convention',      # 约定（L5 输出规范）
    'entity_map',      # 实体映射
    'sample_qa',       # 样例问答（L6 错题 few-shot）
    'quality',         # 数据质量/清洗陷阱（L3，如 $ 前缀、TRIM、CAST 清洗模板）
]

# 全局常驻条目上限（与 crud.knowledge.MAX_PINNED_GLOBAL 一致）
MAX_PINNED_GLOBAL = 20


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
    visibility: Optional[str] = None   # global=管理员全局发布 / personal=个人（默认）
    is_pinned: Optional[int] = None    # 常驻上下文开关（仅 global 可置 1）
    owner_user_id: Optional[int] = None  # 所有者变更（仅管理员更新时生效）

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

    @field_validator('visibility')
    @classmethod
    def validate_visibility(cls, v):
        if v is not None and v not in ('global', 'personal'):
            raise ValueError(f'不支持的可见范围: {v}')
        return v


class KnowledgeResponse(BaseModel):
    """知识库条目响应"""
    id: int
    user_id: int
    owner_name: Optional[str] = None   # 所有者用户名（列表/详情接口附带）
    title: Optional[str]
    content: Optional[str]
    knowledge_type: str = 'note'
    aliases: List[str] = []
    payload: Dict[str, Any] = {}
    scope_schema_id: Optional[int] = None
    visibility: str = 'personal'
    is_pinned: int = 0
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


def _attach_owner_names(items: List[dict]) -> None:
    """就地补充 owner_name（批量查用户名，失败静默留空）"""
    try:
        ids = {d.get('user_id') for d in items if d.get('user_id')}
        if not ids:
            return
        with session_scope() as db:
            rows = db.query(User.id, User.username).filter(User.id.in_(ids)).all()
        name_map = {r[0]: r[1] for r in rows}
        for d in items:
            d['owner_name'] = name_map.get(d.get('user_id'), f"#{d.get('user_id')}")
    except Exception as e:
        logger.warning(f"补充知识所有者名称失败（忽略）: {e}")


def get_all_knowledge(user: dict, limit: int = 20, offset: int = 0,
                      visibility_filter: Optional[str] = None,
                      keyword: Optional[str] = None,
                      type_filter: Optional[str] = None,
                      status_filter: Optional[str] = None,
                      pinned_filter: Optional[str] = None,
                      mine: bool = False) -> tuple:
    """获取知识库条目（全局条目人人可见；个人条目按用户权限过滤）

    status_filter: enabled=仅启用 / disabled=仅禁用 / None=全部
    type_filter: knowledge_type 精确匹配
    pinned_filter: pinned=仅常驻
    mine: True 时仅返回 全局 + 当前用户本人创建 的条目（管理员也不例外，
          供对话页勾选使用——管理全部条目请走管理页，勿混入他人个人条目）
    """
    with session_scope() as db:
        from sqlalchemy import or_
        query = db.query(KnowledgeItem)
        if status_filter == 'enabled':
            query = query.filter(KnowledgeItem.is_active == 1)
        elif status_filter == 'disabled':
            query = query.filter(KnowledgeItem.is_active == 0)
        if type_filter:
            if type_filter == 'note':
                # 历史数据 knowledge_type 可能为 NULL，序列化时归一为 note，筛选需同时匹配
                query = query.filter(or_(
                    KnowledgeItem.knowledge_type == 'note',
                    KnowledgeItem.knowledge_type.is_(None)))
            else:
                query = query.filter(KnowledgeItem.knowledge_type == type_filter)
        if pinned_filter == 'pinned':
            query = query.filter(KnowledgeItem.is_pinned == 1)
        if visibility_filter:
            query = query.filter(KnowledgeItem.visibility == visibility_filter)
        if keyword:
            kw = f"%{keyword.strip()}%"
            query = query.filter(or_(
                KnowledgeItem.title.ilike(kw),
                KnowledgeItem.content.ilike(kw),
            ))
        if mine:
            query = query.filter(or_(
                KnowledgeItem.visibility == 'global',
                KnowledgeItem.user_id == user['user_id']))
        visible_ids = get_visible_knowledge_ids(user)
        if visible_ids is not None and not is_admin(user):
            # 全局条目人人可见；个人条目属主本人或授权清单内的可见
            conds = [KnowledgeItem.visibility == 'global',
                     KnowledgeItem.user_id == user['user_id']]
            if visible_ids:
                conds.append(KnowledgeItem.id.in_(visible_ids))
            query = query.filter(or_(*conds))
        total = query.count()
        items = query.order_by(KnowledgeItem.updated_at.desc()).limit(limit).offset(offset).all()
        # 必须在会话关闭前 expunge，否则 session.close() 会过期属性，
        # 会话外访问 item.id 触发惰性刷新 → DetachedInstanceError
        for obj in items:
            db.expunge(obj)
        return items, total


def get_knowledge_safe(user_id: int, knowledge_id: int = None) -> dict:
    """安全获取知识条目（含用户授权校验，防越权读取；全局条目人人可读）"""
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
        if (item.visibility or 'personal') != 'global':
            if item.user_id != user_id:   # 属主本人始终可读
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


def _validate_visibility_fields(user: dict, data: KnowledgeRequest,
                                current_item: Optional[KnowledgeItem] = None) -> dict:
    """校验 visibility/is_pinned 字段，返回可写入字段。

    visibility：所有用户可设 global（人人可见可召回）/personal；
    is_pinned：仅管理员（常驻注入对全部用户生效，属管理员权限）。
    """
    provided = data.model_fields_set
    fields = {}
    if 'visibility' in provided and data.visibility is not None:
        fields['visibility'] = data.visibility
    if 'is_pinned' in provided and data.is_pinned is not None:
        pinned = 1 if data.is_pinned else 0
        if pinned and not is_admin(user):
            raise HTTPException(status_code=403,
                                detail="常驻上下文仅管理员可设置（会对所有用户生效）")
        target_vis = fields.get('visibility') or (
            (current_item.visibility or 'personal') if current_item else 'personal')
        if pinned and target_vis != 'global':
            raise HTTPException(status_code=400, detail="仅全局知识可设置常驻上下文")
        if pinned:
            from crud.knowledge import MAX_PINNED_GLOBAL
            current_id = current_item.id if current_item else None
            n = knowledge_crud.count_global_pinned()
            if current_item and current_item.is_pinned:
                n -= 1  # 自身已 pin，改内容不占新名额
            if n >= MAX_PINNED_GLOBAL:
                raise HTTPException(
                    status_code=400,
                    detail=f"全局常驻条目已达上限 {MAX_PINNED_GLOBAL}，请先取消部分常驻")
        fields['is_pinned'] = pinned
    return fields


@router.get("/global", response_model=KnowledgeListResponse)
@limiter.limit(LIMIT_READ)
def list_global_knowledge(
    request: Request,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """全局发布且启用的知识条目（人人可见；对话页展示全局规则用）"""
    all_items = knowledge_crud.list_global_active()
    items = all_items[offset:offset + limit]
    return {'items': [_to_dict(i) for i in items], 'total': len(all_items)}


@router.get("", response_model=KnowledgeListResponse)
@limiter.limit(LIMIT_READ)
def list_knowledge(
    request: Request,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    visibility: Optional[str] = Query(None, description="按可见范围过滤：global/personal"),
    keyword: Optional[str] = Query(None, max_length=100, description="按标题/内容模糊搜索"),
    knowledge_type: Optional[str] = Query(None, max_length=30, description="按知识类型过滤"),
    status: Optional[str] = Query(None, description="按状态过滤：enabled/disabled，留空=全部"),
    pinned: Optional[str] = Query(None, description="pinned=仅常驻条目"),
    mine: int = Query(0, ge=0, le=1,
                      description="1=仅返回 全局+本人创建 的条目（对话页勾选用）"),
):
    """获取知识库列表（visibility 过滤对所有用户开放，作用于各自可见范围）"""
    vf = visibility if (visibility in ('global', 'personal')) else None
    st = status if status in ('enabled', 'disabled') else None
    items, total = get_all_knowledge(user, limit, offset, visibility_filter=vf,
                                     keyword=(keyword or '').strip() or None,
                                     type_filter=(knowledge_type or '').strip() or None,
                                     status_filter=st,
                                     pinned_filter=('pinned' if pinned == 'pinned' else None),
                                     mine=bool(mine))
    item_dicts = [_to_dict(item) for item in items]
    _attach_owner_names(item_dicts)
    return {'items': item_dicts, 'total': total}


@router.post("", response_model=KnowledgeResponse)
@limiter.limit(LIMIT_WRITE)
def create_knowledge(
    request: Request,
    data: KnowledgeRequest,
    user: CurrentUser
):
    """创建知识条目"""
    try:
        vis_fields = _validate_visibility_fields(user, data)
        item = knowledge_crud.create(
            user_id=user['user_id'],
            title=data.title,
            content=data.content or '',
            knowledge_type=data.knowledge_type or 'note',
            aliases=json.dumps(data.aliases or [], ensure_ascii=False),
            payload=json.dumps(data.payload or {}, ensure_ascii=False),
            scope_schema_id=data.scope_schema_id,
            visibility=vis_fields.get('visibility', 'personal'),
            is_pinned=vis_fields.get('is_pinned', 0),
        )
        knowledge_crud.record_version(item.id, 'create', user['user_id'])
        log_audit(user, "create_knowledge",
                  f"title={data.title} type={data.knowledge_type} "
                  f"visibility={vis_fields.get('visibility', 'personal')} "
                  f"pinned={vis_fields.get('is_pinned', 0)}")
        return _to_dict(item)
    except HTTPException:
        raise
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
        item = knowledge_crud.get_one(id=knowledge_id, is_active=1)
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在或已删除")
        # 非管理员：本人条目 / 全局条目 / 授权清单内条目可读
        if (visible_ids is not None and item.user_id != user['user_id']
                and knowledge_id not in visible_ids):
            raise HTTPException(status_code=404, detail="知识不存在或已删除")

        result = _to_dict(item)
        _attach_owner_names([result])
        return result
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
        if 'owner_user_id' in provided and data.owner_user_id is not None:
            # 所有者变更：仅管理员；目标用户必须存在（创建者永远是本人，创建接口不受理此字段）
            if not is_admin(user):
                raise HTTPException(status_code=403, detail="仅管理员可更改知识所有者")
            with session_scope() as db:
                target = db.query(User.id).filter(User.id == data.owner_user_id).first()
            if not target:
                raise HTTPException(status_code=400, detail="目标用户不存在")
            if data.owner_user_id != item.user_id:
                update_fields['user_id'] = data.owner_user_id
        update_fields.update(_validate_visibility_fields(user, data, item))

        knowledge_crud.update(knowledge_id, **update_fields)
        knowledge_crud.record_version(knowledge_id, 'update', user['user_id'])
        owner_note = f" owner->{data.owner_user_id}" if (
            'owner_user_id' in provided and data.owner_user_id is not None) else ""
        log_audit(user, "update_knowledge", f"id={knowledge_id}{owner_note}")
        result = _to_dict(knowledge_crud.get_by_id(knowledge_id))
        _attach_owner_names([result])
        return result
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
    """删除知识（物理删除，条目及其全部版本快照一并清除；所有者或管理员）"""
    try:
        item = knowledge_crud.get_by_id(knowledge_id)
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能删除自己创建的知识")

        knowledge_crud.hard_delete(knowledge_id)
        log_audit(user, "delete_knowledge", f"id={knowledge_id}")
        return {"message": "知识已彻底删除（含全部版本历史）"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RestoreRequest(BaseModel):
    version_no: int


@router.get("/{knowledge_id}/versions")
@limiter.limit(LIMIT_READ)
def list_knowledge_versions(
    request: Request,
    knowledge_id: int,
    user: CurrentUser
):
    """知识条目版本历史（含快照；属主或管理员）"""
    item = knowledge_crud.get_by_id(knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识不存在")
    if not is_admin(user) and item.user_id != user['user_id']:
        raise HTTPException(status_code=403, detail="只能查看自己创建的知识的版本")
    return {'items': knowledge_crud.list_versions(knowledge_id)}


@router.post("/{knowledge_id}/restore", response_model=KnowledgeResponse)
@limiter.limit(LIMIT_WRITE)
def restore_knowledge_version(
    request: Request,
    knowledge_id: int,
    body: RestoreRequest,
    user: CurrentUser
):
    """恢复知识条目到指定版本（属主或管理员；删除态条目恢复后重新启用）"""
    try:
        item = knowledge_crud.get_by_id(knowledge_id)  # get_by_id 含删除态行，删除后仍可恢复
        if not item:
            raise HTTPException(status_code=404, detail="知识不存在")
        if not is_admin(user) and item.user_id != user['user_id']:
            raise HTTPException(status_code=403, detail="只能恢复自己创建的知识")

        snap = knowledge_crud.get_version_snapshot(knowledge_id, body.version_no)
        if not snap:
            raise HTTPException(status_code=404, detail=f"版本 {body.version_no} 不存在")

        restore_fields = {
            'title': snap.get('title'),
            'content': snap.get('content'),
            'knowledge_type': snap.get('knowledge_type') or 'note',
            'aliases': snap.get('aliases'),
            'payload': snap.get('payload'),
            'scope_schema_id': snap.get('scope_schema_id'),
            'visibility': snap.get('visibility') or 'personal',
            'is_pinned': snap.get('is_pinned') or 0,
            'is_active': 1,  # 恢复即重新启用
        }
        # 常驻注入对全部用户生效，仅管理员可设置——非管理员恢复不得借历史快照绕过
        if not is_admin(user) and restore_fields['is_pinned']:
            restore_fields['is_pinned'] = 0
        knowledge_crud.update(knowledge_id, **restore_fields)
        knowledge_crud.record_version(knowledge_id, 'restore', user['user_id'])
        log_audit(user, "restore_knowledge", f"id={knowledge_id} version={body.version_no}")
        return _to_dict(knowledge_crud.get_by_id(knowledge_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复知识版本失败: {e}")
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
        from core.recall_scope import build_recall_scope
        from core.ret_retriever import SchemaRetriever
        retriever = SchemaRetriever(user=user, user_id=user['user_id'])
        result = retriever.recall_knowledge(
            query=body.query,
            scope_schema_id=body.scope_schema_id,
            scope=build_recall_scope(user),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"知识召回失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
