# -*- coding: UTF-8 -*-
"""知识库改造回归 — 全局常驻 / 版本化恢复 / 召回可见性 / 用户默认勾选

覆盖五条性质：
  1. 版本快照：create/update/delete/restore 全程留痕，restore 可从删除态恢复并重新启用
  2. 权限：非管理员不可发布全局 / 不可 pin 个人条目；pin 仅全局且受上限约束
  3. 常驻注入：_get_global_rules_content 只取 global+is_pinned 条目，预算截断生效
  4. 召回可见性：search_matched_items 的 global 人人可见、personal 仅属主/被授权者
  5. 用户默认勾选：_get_user_default_knowledge_ids 读取 user_preferences（缺失/损坏容错）
"""
import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from crud.knowledge import MAX_PINNED_GLOBAL, knowledge_crud
from models.knowledge import KnowledgeItem, KnowledgeVersion


@pytest.fixture()
def kb_db(monkeypatch):
    """内存 SQLite 建 knowledge_items / knowledge_versions / user_preferences，
    替换 crud.knowledge 与 conversation_router 的 session_scope"""
    engine = create_engine('sqlite://')
    KnowledgeItem.__table__.create(engine)
    KnowledgeVersion.__table__.create(engine)
    from models.preference import UserPreference
    UserPreference.__table__.create(engine)
    # list_versions 现需联 users 表取操作人用户名
    from models.user import User
    User.__table__.create(engine)
    # expire_on_commit=False 与生产 sessionmaker 语义一致（db/engine.py）
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def fake_session_scope(*args, **kwargs):
        # 兼容 BaseCrud 的 session_scope(telemetry=, logs=) 调用形态
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # 关键：BaseCrud 的通用方法（create/update/list…）解析的是 crud.base 命名空间的
    # session_scope，必须补丁权威位置；crud.knowledge 内直接使用与新方法也要覆盖
    monkeypatch.setattr('crud.base.session_scope', fake_session_scope)
    monkeypatch.setattr('crud.knowledge.session_scope', fake_session_scope)
    monkeypatch.setattr('app.routers.conversation_router.session_scope',
                        fake_session_scope)
    return {'factory': factory}


def _add_item(factory, **kw):
    s = factory()
    item = KnowledgeItem(user_id=kw.pop('user_id', 1),
                         title=kw.pop('title', 't'),
                         content=kw.pop('content', 'c'),
                         **kw)
    s.add(item)
    s.commit()
    s.refresh(item)
    iid = item.id
    s.close()
    return iid


def _get_item(factory, iid):
    s = factory()
    item = s.query(KnowledgeItem).filter(KnowledgeItem.id == iid).first()
    s.expunge(item)
    s.close()
    return item


# ── 1. 版本快照 ──────────────────────────────────────────────────

def test_version_full_lifecycle(kb_db):
    iid = _add_item(kb_db['factory'], title='原始', content='v1 内容')
    knowledge_crud.record_version(iid, 'create', 1)
    knowledge_crud.update(iid, content='v2 内容')
    knowledge_crud.record_version(iid, 'update', 1)
    knowledge_crud.update(iid, is_active=0)
    knowledge_crud.record_version(iid, 'delete', 1)

    versions = knowledge_crud.list_versions(iid)
    assert [v['action'] for v in versions] == ['delete', 'update', 'create']
    assert versions[2]['snapshot']['content'] == 'v1 内容'
    assert versions[0]['snapshot']['is_active'] == 0

    # 从 create 版本恢复 → 内容回滚 + 重新启用
    snap = knowledge_crud.get_version_snapshot(iid, 1)
    knowledge_crud.update(iid, **{k: snap[k] for k in
                                  ('title', 'content', 'knowledge_type', 'aliases',
                                   'payload', 'scope_schema_id', 'visibility',
                                   'is_pinned', 'is_active')})
    knowledge_crud.record_version(iid, 'restore', 1)
    item = _get_item(kb_db['factory'], iid)
    assert item.is_active == 1
    assert item.content == 'v1 内容'
    assert len(knowledge_crud.list_versions(iid)) == 4


def test_version_missing_item_and_version(kb_db):
    assert knowledge_crud.record_version(999, 'create', 1) == 0
    assert knowledge_crud.get_version_snapshot(999, 1) is None


# ── 2. 权限校验（路由层） ─────────────────────────────────────────

def _make_user(user_id=1, role='admin', roles=None):
    return {'user_id': user_id, 'role': role, 'roles': roles or [role]}


def test_validate_visibility_admin_only(kb_db):
    from app.routers.knowledge_router import KnowledgeRequest, _validate_visibility_fields
    from fastapi import HTTPException

    data = KnowledgeRequest(visibility='global')
    # 管理员可发布全局
    fields = _validate_visibility_fields(_make_user(role='admin'), data)
    assert fields['visibility'] == 'global'
    # 普通用户 403
    with pytest.raises(HTTPException) as ei:
        _validate_visibility_fields(_make_user(user_id=2, role='user'), data)
    assert ei.value.status_code == 403


def test_validate_pin_requires_global(kb_db):
    from app.routers.knowledge_router import KnowledgeRequest, _validate_visibility_fields
    from fastapi import HTTPException

    # 个人条目 pin → 400
    with pytest.raises(HTTPException) as ei:
        _validate_visibility_fields(
            _make_user(), KnowledgeRequest(is_pinned=1),
            KnowledgeItem(id=9, user_id=1, visibility='personal'))
    assert ei.value.status_code == 400
    # 全局条目 pin → 通过
    fields = _validate_visibility_fields(
        _make_user(), KnowledgeRequest(is_pinned=1),
        KnowledgeItem(id=9, user_id=1, visibility='global'))
    assert fields['is_pinned'] == 1


def test_pin_cap(kb_db, monkeypatch):
    from app.routers.knowledge_router import KnowledgeRequest, _validate_visibility_fields
    from fastapi import HTTPException

    monkeypatch.setattr(knowledge_crud, 'count_global_pinned',
                        lambda: MAX_PINNED_GLOBAL)
    with pytest.raises(HTTPException) as ei:
        _validate_visibility_fields(
            _make_user(), KnowledgeRequest(is_pinned=1),
            KnowledgeItem(id=9, user_id=1, visibility='global', is_pinned=0))
    assert ei.value.status_code == 400
    # 自身已 pin：改内容不占新名额
    fields = _validate_visibility_fields(
        _make_user(), KnowledgeRequest(is_pinned=1),
        KnowledgeItem(id=9, user_id=1, visibility='global', is_pinned=1))
    assert fields['is_pinned'] == 1


# ── 3. 全局常驻注入 ──────────────────────────────────────────────

def test_global_rules_only_pinned_global(kb_db, monkeypatch):
    from app.routers.conversation_router import _get_global_rules_content
    # 三条：pin 全局 / 未 pin 全局 / pin 个人 → 只有第一条进常驻
    _add_item(kb_db['factory'], title='规则A', content='规则A内容',
              visibility='global', is_pinned=1)
    _add_item(kb_db['factory'], title='规则B', content='规则B内容',
              visibility='global', is_pinned=0)
    _add_item(kb_db['factory'], title='规则C', content='规则C内容',
              visibility='personal', is_pinned=1)
    text, n = _get_global_rules_content()
    assert n == 1
    assert '规则A内容' in text and '规则A' in text
    assert '规则B内容' not in text and '规则C内容' not in text


def test_global_rules_budget_truncation(kb_db, monkeypatch):
    import app.routers.conversation_router as cr
    monkeypatch.setattr(cr, '_GLOBAL_RULE_ITEM_BUDGET', 50)
    monkeypatch.setattr(cr, '_GLOBAL_RULE_TOTAL_BUDGET', 80)
    _add_item(kb_db['factory'], title='长规则1', content='x' * 60,
              visibility='global', is_pinned=1)
    _add_item(kb_db['factory'], title='长规则2', content='y' * 60,
              visibility='global', is_pinned=1)
    text, n = cr._get_global_rules_content()
    assert '…(截断)' in text           # 单条超预算截断
    assert n == 1                      # 总预算触顶，只注入第一条


# ── 4. 召回可见性 ────────────────────────────────────────────────

def test_recall_visibility_filter(kb_db):
    kw = {'订单'}
    iid_global = _add_item(kb_db['factory'], user_id=1, title='订单口径',
                           content='订单 = 已支付订单', visibility='global')
    iid_mine = _add_item(kb_db['factory'], user_id=2, title='订单黑话',
                         content='我的订单口径', visibility='personal')
    iid_other = _add_item(kb_db['factory'], user_id=3, title='订单机密',
                          content='他人订单口径', visibility='personal')

    # 属主（user 2）：global + 自己的 personal，看不到 user 3 的
    got = {d['id'] for d in knowledge_crud.search_matched_items(
        kw, owner_user_id=2)}
    assert iid_global in got and iid_mine in got and iid_other not in got

    # 被授权者（user 4 带 visible_ids）：global + 授权条目
    got = {d['id'] for d in knowledge_crud.search_matched_items(
        kw, owner_user_id=4, visible_ids={iid_other})}
    assert iid_global in got and iid_other in got and iid_mine not in got

    # 无授权者（user 4）：只有 global
    got = {d['id'] for d in knowledge_crud.search_matched_items(
        kw, owner_user_id=4, visible_ids=set())}
    assert got == {iid_global}


# ── 5. 用户默认勾选 ──────────────────────────────────────────────

def test_user_default_knowledge_ids(kb_db):
    from app.routers.conversation_router import _get_user_default_knowledge_ids
    from models.preference import UserPreference

    assert _get_user_default_knowledge_ids(9) == []   # 无记录 → 空

    s = kb_db['factory']()
    s.add(UserPreference(user_id=9, pref_key='default_knowledge_ids',
                         pref_value=json.dumps([3, 7])))
    s.commit()
    s.close()
    assert _get_user_default_knowledge_ids(9) == [3, 7]

    # 损坏 JSON 容错
    s = kb_db['factory']()
    row = s.query(UserPreference).filter(UserPreference.user_id == 9).first()
    row.pref_value = '{broken'
    s.commit()
    s.close()
    assert _get_user_default_knowledge_ids(9) == []
