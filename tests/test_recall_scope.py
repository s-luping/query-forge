# -*- coding: UTF-8 -*-
"""P2 召回/权限解耦（RecallScope）回归 — docs/07-ChatSQL模块化与全链路留痕设计.md §3.2

黄金对照原则：改造前行为 = permissions 模块实时查权限 → 裁剪；改造后 = 编排层
构建 RecallScope 快照 → 召回模块纯数据过滤。本文件断言：
1. build_recall_scope 四项快照与 permissions 函数返回值一致（含失败降级语义）
2. 显式传 scope 时，app.permissions 全部函数即使抛错也不影响召回（隔离性证明）
3. 裁剪结果逐字段等价（NONE 剔除 / 默认放行 / 无 column_id 放行）
4. 知识召回、表关系、聚合兜底均消费 scope 数据
"""
from types import SimpleNamespace

import pytest

from core.recall_scope import RecallScope, build_recall_scope
from core.ret_retriever import SchemaRetriever

ADMIN = {'user_id': 1, 'role': 'admin'}
USER = {'user_id': 9, 'role': 'user'}


def _row(schema, table, column, column_id=0, sample_values=None,
         sensitive_level='public', schema_id=1):
    return SimpleNamespace(
        schema_name=schema, table_name=table, column_name=column,
        column_id=column_id, sample_values=sample_values,
        sensitive_level=sensitive_level, is_dimension=False, is_measure=False,
        column_type='varchar(64)', column_description='', column_key='',
        foreign_key='', schema_id=schema_id)


# ---------- 1. build_recall_scope 快照构建 ----------

def test_build_recall_scope_covers_all_four(monkeypatch):
    import app.permissions as perm
    monkeypatch.setattr(perm, 'get_visible_schema_ids', lambda u: [1, 2])
    monkeypatch.setattr(perm, 'get_table_grants_by_schema', lambda u: {1: [10, 11]})
    monkeypatch.setattr(perm, 'get_column_access_map', lambda u, **kw: {31: 'FILTER'})
    monkeypatch.setattr(perm, 'get_visible_knowledge_ids', lambda u: [3, 7])

    scope = build_recall_scope(USER)
    assert scope.visible_schema_ids == [1, 2]
    assert scope.table_grants == {1: [10, 11]}
    assert scope.column_access == {31: 'FILTER'}
    assert scope.visible_knowledge_ids == {3, 7}


def test_build_recall_scope_admin_all_none(monkeypatch):
    import app.permissions as perm
    monkeypatch.setattr(perm, 'get_visible_schema_ids', lambda u: None)
    monkeypatch.setattr(perm, 'get_table_grants_by_schema', lambda u: {})
    monkeypatch.setattr(perm, 'get_column_access_map', lambda u, **kw: {})
    monkeypatch.setattr(perm, 'get_visible_knowledge_ids', lambda u: None)

    scope = build_recall_scope(ADMIN)
    assert scope.visible_schema_ids is None       # None = 全部可见
    assert scope.visible_knowledge_ids is None    # None = 知识不限制


def test_build_recall_scope_knowledge_failure_degrades_to_none(monkeypatch):
    import app.permissions as perm
    monkeypatch.setattr(perm, 'get_visible_schema_ids', lambda u: [1])
    monkeypatch.setattr(perm, 'get_table_grants_by_schema', lambda u: {})
    monkeypatch.setattr(perm, 'get_column_access_map', lambda u, **kw: {})
    def _boom(u):
        raise RuntimeError('db down')
    monkeypatch.setattr(perm, 'get_visible_knowledge_ids', _boom)

    scope = build_recall_scope(USER)
    assert scope.visible_knowledge_ids is None, '知识可见性失败降级为不限制（与原内联 try/except 一致）'
    assert scope.visible_schema_ids == [1]        # 其余三项不受影响


# ---------- 2. 隔离性：显式 scope 时 permissions 全挂也不影响召回 ----------

def _patch_data_layer(monkeypatch, rows):
    """替换召回依赖的数据层（schema_service），permissions 不参与"""
    import services.schema_service as ss
    captured = {}
    def fake_iter_field_rows(schema_name=None, table_names=None,
                             visible_schema_ids=None, table_grants_by_schema=None):
        captured['visible'] = visible_schema_ids
        captured['grants'] = table_grants_by_schema
        captured['tables'] = table_names
        return list(rows)
    monkeypatch.setattr(ss, 'iter_field_rows', fake_iter_field_rows)
    monkeypatch.setattr(ss, 'field_count', lambda schema_name=None: 999999)
    return captured


def _break_permissions(monkeypatch):
    import app.permissions as perm
    def _boom(*a, **kw):
        raise RuntimeError('permissions must not be called when scope given')
    for fn in ('get_visible_schema_ids', 'get_table_grants_by_schema',
               'get_column_access_map', 'get_visible_knowledge_ids',
               'filter_fields_by_permission'):
        monkeypatch.setattr(perm, fn, _boom)


def test_explicit_scope_recalls_without_permissions(monkeypatch):
    """隔离性证明：scope 显式传入时，permissions 模块整体不可用召回仍正常"""
    _break_permissions(monkeypatch)
    rows = [_row('db1', 't1', 'c1', column_id=11),
            _row('db1', 't1', 'c2', column_id=12)]
    _patch_data_layer(monkeypatch, rows)

    scope = RecallScope(visible_schema_ids=[1], table_grants={1: [10]},
                        column_access={11: 'SELECT', 12: 'FILTER'})
    r = SchemaRetriever(user=USER, user_id=9, scope=scope)
    r.vector_error = 'skip'   # 跳过向量加载，走 DB 召回
    out = r.recall_fields(['c1'], schema_name='db1', scope=scope)
    cols = {f['column_name'] for f in out}
    assert cols == {'c1'}, '关键词 c1 只命中 c1；FILTER 列仍在数据层、NONE 才剔除'


def test_scope_none_columns_dropped_golden(monkeypatch):
    """黄金对照：字段级裁剪与原 filter_fields_by_permission 逐字段等价"""
    rows = [_row('db1', 't1', 'c_pub', column_id=11),
            _row('db1', 't1', 'c_fil', column_id=12),
            _row('db1', 't1', 'c_non', column_id=13),
            _row('db1', 't1', 'c_noid', column_id=0)]
    captured = _patch_data_layer(monkeypatch, rows)

    scope = RecallScope(visible_schema_ids=[1], table_grants={1: [10]},
                        column_access={11: 'SELECT', 12: 'FILTER', 13: 'NONE'})
    r = SchemaRetriever(user=USER, user_id=9)
    out = r.get_field_rows('db1', scope=scope)
    assert [x.column_name for x in out] == ['c_pub', 'c_fil', 'c_noid'], \
        'NONE 剔除、SELECT/FILTER 保留、无 column_id 默认放行（= 原实现）'
    assert captured['visible'] == [1] and captured['grants'] == {1: [10]}

    # 无 column_id 整批放行（原实现 col_ids 为空短路）
    rows2 = [_row('db1', 't1', 'x', column_id=0)]
    _patch_data_layer(monkeypatch, rows2)
    out2 = r.get_field_rows('db1', scope=scope)
    assert len(out2) == 1


# ---------- 3. 知识召回 / 表关系 / 聚合兜底消费 scope ----------

def test_recall_knowledge_uses_scope_visible_ids(monkeypatch):
    import crud.knowledge as ck
    seen = {}

    class _FakeCrud:
        def search_matched_items(self, kw_set, scope_schema_id=None, limit=12,
                                 owner_user_id=None, visible_ids=None):
            seen['visible_ids'] = visible_ids
            seen['owner'] = owner_user_id
            return []
    monkeypatch.setattr(ck, 'knowledge_crud', _FakeCrud())

    scope = RecallScope(visible_schema_ids=[1],
                        visible_knowledge_ids={5, 6})
    r = SchemaRetriever(user=USER, user_id=9)
    r.keyword_extractor = SimpleNamespace(extract=lambda q, top_k=10: ['费用'])
    r.recall_knowledge('费用', scope=scope)
    assert seen['visible_ids'] == {5, 6}
    assert seen['owner'] == 9


def test_relations_text_uses_scope(monkeypatch):
    from core import ret_retriever as rr

    class _FakeRelationCrud:
        def __init__(self):
            self.mode = None
        def list_by_schemas(self, ids):
            self.mode = ('by_schemas', ids)
            return []
        def list_all(self, order_by=None):
            self.mode = ('all',)
            return []
    fake = _FakeRelationCrud()
    monkeypatch.setattr(rr, 'relation_crud', fake)

    r = SchemaRetriever(user=USER, user_id=9)
    r.get_relations_text(['t1'], scope=RecallScope(visible_schema_ids=[1, 2]))
    assert fake.mode == ('by_schemas', [1, 2])

    fake2 = _FakeRelationCrud()
    monkeypatch.setattr(rr, 'relation_crud', fake2)
    r.get_relations_text(['t1'], scope=RecallScope(visible_schema_ids=[]))
    assert fake2.mode is None, '可见库为空时应短路返回空串，不查关系表'

    fake3 = _FakeRelationCrud()
    monkeypatch.setattr(rr, 'relation_crud', fake3)
    r.get_relations_text(['t1'], scope=RecallScope(visible_schema_ids=None))
    assert fake3.mode == ('all',)


def test_aggregate_tables_fallback_uses_scope(monkeypatch):
    import services.schema_service as ss
    seen = {}
    def fake_list_tables(db, schema_name=None, visible_schema_ids=None,
                         table_grants_by_schema=None):
        seen['visible'] = visible_schema_ids
        seen['grants'] = table_grants_by_schema
        return [('t1',)]
    monkeypatch.setattr(ss, 'list_tables', fake_list_tables)
    rows = [_row('db1', 't1', 'c1', column_id=11)]
    _patch_data_layer(monkeypatch, rows)

    scope = RecallScope(visible_schema_ids=[1], table_grants={1: [10]},
                        column_access={11: 'SELECT'})
    r = SchemaRetriever(user=USER, user_id=9)
    agg = r.aggregate_tables([], schema_name='db1', scope=scope)   # 空召回 → 兜底分支
    assert seen['visible'] == [1] and seen['grants'] == {1: [10]}
    assert agg['tables'] == ['t1'] and 'db1.t1.c1' in agg['all_fields']


# ---------- 4. 遗留兼容：不传 scope 时惰性构建（行为等同直接查权限） ----------

def test_default_scope_lazy_build(monkeypatch):
    import app.permissions as perm
    monkeypatch.setattr(perm, 'get_visible_schema_ids', lambda u: [2])
    monkeypatch.setattr(perm, 'get_table_grants_by_schema', lambda u: {2: [20]})
    monkeypatch.setattr(perm, 'get_column_access_map',
                        lambda u, **kw: {21: 'NONE', 22: 'SELECT'})
    monkeypatch.setattr(perm, 'get_visible_knowledge_ids', lambda u: None)
    rows = [_row('db2', 't2', 'secret', column_id=21),
            _row('db2', 't2', 'open', column_id=22)]
    _patch_data_layer(monkeypatch, rows)

    r = SchemaRetriever(user=USER, user_id=9)   # 未传 scope
    out = r.get_field_rows('db2')
    assert [x.column_name for x in out] == ['open'], '惰性构建的快照同样剔除 NONE 字段'
    # 快照已缓存：再次调用不再触发 permissions（换成抛错版本验证）
    _break_permissions(monkeypatch)
    out2 = r.get_field_rows('db2')
    assert [x.column_name for x in out2] == ['open']


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
