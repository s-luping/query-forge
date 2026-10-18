# -*- coding: UTF-8 -*-
"""会话搜索回归 — list_paged 关键字过滤（标题 / 消息内容）+ 权限边界

覆盖性质：
  1. 关键字命中标题 → 返回对应会话
  2. 标题未命中但会话内消息内容命中 → 返回对应会话（EXISTS 子查询）
  3. 关键字为 None/空白 → 不过滤，返回全量
  4. 非管理员只见自己的会话；搜索命中他人会话不泄漏
  5. 搜索结果 total 与分页一致
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from crud.conversation import conversation_crud
from models.conversation import Conversation, ConversationMessage


@pytest.fixture()
def conv_db(monkeypatch):
    """内存 SQLite 建 conversations / conversation_messages，替换 crud.base.session_scope"""
    engine = create_engine('sqlite://')
    # 导入 FK 链上的模型模块，使目标表在共享 MainBase MetaData 中可解析
    # （conversations.schema_id→db_schemas→data_sources；仅解析不建表，SQLite 默认不强制 FK）
    from models.schema import DbSchema  # noqa: F401
    from models.datasource import DataSource  # noqa: F401
    Conversation.__table__.create(engine)
    ConversationMessage.__table__.create(engine)
    # expire_on_commit=False 与生产 sessionmaker 语义一致（db/engine.py）
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def fake_session_scope(*args, **kwargs):
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # 双补丁：BaseCrud 通用方法解析 crud.base 命名空间；conversation 模块顶层
    # from-import 了 session_scope，list_paged 用的是 crud.conversation 自己的名字
    monkeypatch.setattr('crud.base.session_scope', fake_session_scope)
    monkeypatch.setattr('crud.conversation.session_scope', fake_session_scope)
    return {'factory': factory}


def _add_conv(factory, user_id, title, messages=()):
    """建会话 + 若干消息，返回会话 id"""
    s = factory()
    conv = Conversation(user_id=user_id, title=title, db_type='sqlite')
    s.add(conv)
    s.flush()
    for role, content in messages:
        s.add(ConversationMessage(conversation_id=conv.id, role=role, content=content))
    s.commit()
    cid = conv.id
    s.close()
    return cid


def test_search_by_title(conv_db):
    f = conv_db['factory']
    _add_conv(f, 1, '奶茶月度收入统计', messages=[('user', '查一下收入')])
    _add_conv(f, 1, 'sakila 租赁分析', messages=[('user', '租赁数')])

    items, total = conversation_crud.list_paged(1, search='奶茶')
    assert total == 1
    assert items[0].title == '奶茶月度收入统计'


def test_search_by_message_content(conv_db):
    """标题不命中、消息内容命中 → 仍应返回该会话"""
    f = conv_db['factory']
    cid = _add_conv(f, 1, '随便聊聊',
                    messages=[('user', '查订单表的总金额'),
                              ('assistant', 'SELECT SUM(amount) FROM orders')])
    _add_conv(f, 1, '另一个话题', messages=[('user', '电影租赁')])

    items, total = conversation_crud.list_paged(1, search='SUM(amount)')
    assert total == 1
    assert items[0].id == cid


def test_search_empty_returns_all(conv_db):
    """None / 空白关键字 → 不过滤"""
    f = conv_db['factory']
    _add_conv(f, 1, 'A')
    _add_conv(f, 1, 'B')

    assert conversation_crud.list_paged(1, search=None)[1] == 2
    assert conversation_crud.list_paged(1, search='   ')[1] == 2


def test_search_respects_user_scope(conv_db):
    """非管理员搜索命中他人会话 → 不泄漏；管理员可跨用户命中"""
    f = conv_db['factory']
    other_cid = _add_conv(f, 99, '他人会话：库存盘点',
                          messages=[('user', '盘点库存表')])
    _add_conv(f, 1, '自己的会话', messages=[('user', '查收入')])

    items, total = conversation_crud.list_paged(1, is_admin=False, search='库存')
    assert total == 0

    items, total = conversation_crud.list_paged(None, is_admin=True, search='库存')
    assert total == 1
    assert items[0].id == other_cid


def test_search_paging_total(conv_db):
    """搜索 + 分页：total 为命中总数，offset 翻页不重不漏"""
    f = conv_db['factory']
    for i in range(5):
        _add_conv(f, 1, f'收入专题 {i}')

    page1, total = conversation_crud.list_paged(1, limit=3, offset=0, search='收入')
    page2, _ = conversation_crud.list_paged(1, limit=3, offset=3, search='收入')
    all_ids = {c.id for c in conversation_crud.list_paged(1, limit=10, offset=0, search='收入')[0]}
    assert total == 5
    assert len(page1) == 3 and len(page2) == 2
    assert {c.id for c in page1} | {c.id for c in page2} == all_ids
