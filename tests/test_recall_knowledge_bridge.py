# -*- coding: UTF-8 -*-
"""召回-知识桥接回归 — 防护 2026-10-19 conv8「24-09费用合计」连续 5 轮误拦截事故

事故链：用户问「24-09公司费用合计科目值是多少」→ 向量召回只回 ODS 杂表/EPMDEV
视图（DM 事实表列名是通用英文、无采样值，业务问法排不进 top-K）→ 知识自动召回
虽命中 entity_map（费用→AA0003、公司汇总→EETotal、项目汇总→PJTotal），但
① related_tables 只认 relation 类型，entity_map 不扩表；
② 追问轮判断 prompt 不注入自动召回知识（首轮注、追问不注的不对称）；
③ 首轮 10 张杂表经 keep_first 占满 MAX_TABLES，知识表即使扩进来也被裁掉。
→ 判断步每轮都以"缺实采值/缺表"拦截，用户越补充越偏。

覆盖性质：
  1. recall_knowledge：非 relation 类型的 payload.related_tables 也参与扩表
  2. recall_fields：向量满载时 DB 兜底保留 top_k//3 名额；无向量时兜底全量（原降级行为）
  3. 追问轮判断 prompt 并入自动召回知识（entity_map 口径必须进判断步）
  4. 追问轮知识扩表并入 keep_first 且标记 recall_source='knowledge'
  5. seed 脚本两条 DM 知识声明 related_tables=4 张事实表
"""
import importlib.util
from pathlib import Path

import pytest

DM_FACT_TABLES = [
    'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC',
    'DM_KEY_ACTUAL_INDICATOR_DATA',
    'DM_KEY_BUDGET_INDICATOR_DATA_METRIC',
    'DM_KEY_BUDGET_INDICATOR_DATA',
]

ENTITY_MAP_TEXT = ('【领域知识】\n费用/总费用 → ACCOUNT=AA0003（费用合计）；'
                   '部门/组织/公司主体 → ENTITY（全公司合计用 EETotal）；'
                   '产品线/项目 → PROJECT_LINE（全部合计用 PJTotal）')


# ---------- 1. recall_knowledge：非 relation 类型的 related_tables 扩表 ----------

def test_recall_knowledge_collects_related_tables_from_payload(monkeypatch):
    """entity_map/note 的 payload.related_tables 必须进 related_tables（桥接召回）"""
    from core.ret_retriever import SchemaRetriever

    retriever = SchemaRetriever(user={'user_id': 1, 'role': 'admin'}, user_id=1)
    items = [
        {'id': 14, 'title': '口语词到科目编码映射', 'knowledge_type': 'entity_map',
         'aliases': ['费用'], 'content': ENTITY_MAP_TEXT,
         'payload': {'related_tables': DM_FACT_TABLES[:2]}},
        {'id': 9, 'title': '事实表选择', 'knowledge_type': 'note',
         'aliases': ['实际数'], 'content': '选表口径',
         'payload': {'related_tables': DM_FACT_TABLES[:3]}},
        {'id': 20, 'title': '关系条目', 'knowledge_type': 'relation',
         'aliases': [], 'content': 'A=B',
         'payload': {'left': {'table': 'DIM_A'}, 'right': {'table': 'DIM_B'}}},
        {'id': 21, 'title': '无关联表', 'knowledge_type': 'note',
         'aliases': [], 'content': 'x', 'payload': {}},
    ]
    monkeypatch.setattr('crud.knowledge.knowledge_crud.search_matched_items',
                        lambda *a, **kw: list(items))
    monkeypatch.setattr('app.permissions.get_visible_knowledge_ids',
                        lambda user: None)

    out = retriever.recall_knowledge('24-09公司费用合计科目值是多少',
                                     keywords=['费用', '科目'])
    # 顺序按命中条目展开，去重；relation 两侧表照旧收集
    assert out['related_tables'] == [
        'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC',
        'DM_KEY_ACTUAL_INDICATOR_DATA',
        'DM_KEY_BUDGET_INDICATOR_DATA_METRIC',
        'DIM_A', 'DIM_B',
    ]
    assert len(out['items']) == 4
    assert 'AA0003' in out['prompt_text']


# ---------- 2. recall_fields：向量满载时 DB 兜底保留名额 ----------

def _make_retriever():
    from core.ret_retriever import SchemaRetriever
    return SchemaRetriever(user={'user_id': 1, 'role': 'admin'}, user_id=1)


def test_recall_fields_reserves_quota_for_db_fallback(monkeypatch):
    """向量 100 条满载时，DB 关键词兜底不得被整体截断（保留 top_k//3 名额）"""
    retriever = _make_retriever()
    retriever.vector_loaded = True          # 跳过懒加载/索引构建
    vec = [{'schema_name': 'ODS', 'table_name': f'ODS_JUNK_{i}',
            'column_name': f'C{i}', 'recall_source': 'vector'}
           for i in range(100)]
    db = [{'schema_name': 'DM', 'table_name': 'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC',
           'column_name': col, 'recall_source': 'db'}
          for col in ('ACCOUNT', 'ENTITY', 'PROJECT_LINE', 'PERIODS', 'YEARS')]
    monkeypatch.setattr(retriever, 'search_vector', lambda *a, **kw: list(vec))
    monkeypatch.setattr(retriever, '_filter_recalled_by_permission',
                        lambda res, sn=None, scope=None: res)
    monkeypatch.setattr(retriever, 'recall_from_db', lambda kws, sn=None, scope=None: list(db))
    monkeypatch.setattr('core.ret_retriever.get_vector_config', lambda key: 100)

    out = retriever.recall_fields(['科目'], schema_name=None, query='费用合计科目')
    assert len(out) == 100
    db_kept = [d for d in out if d.get('recall_source') == 'db']
    assert len(db_kept) == 5, 'DB 兜底必须保留名额，不得被向量结果挤出'
    assert len([d for d in out if d.get('recall_source') == 'vector']) == 95


def test_recall_fields_db_only_full_when_vector_absent(monkeypatch):
    """无向量结果时兜底全量返回（原降级行为不回归）"""
    retriever = _make_retriever()
    retriever.vector_loaded = True
    db = [{'schema_name': 'DM', 'table_name': 'DM_KEY_ACTUAL_INDICATOR_DATA',
           'column_name': f'COL_{i}', 'recall_source': 'db'}
          for i in range(60)]
    monkeypatch.setattr(retriever, 'search_vector', lambda *a, **kw: None)
    monkeypatch.setattr(retriever, 'recall_from_db', lambda kws, sn=None, scope=None: list(db))
    monkeypatch.setattr('core.ret_retriever.get_vector_config', lambda key: 100)

    out = retriever.recall_fields(['科目'], schema_name=None, query='费用合计科目')
    assert len(out) == 60
    assert all(d.get('recall_source') == 'db' for d in out)


# ---------- 2b. 全库直通：全库字段总数低于 VECTOR_INDEX_THRESHOLD 时免召回 ----------

class _FakeRow:
    def __init__(self, schema_name, table_name):
        self.schema_name = schema_name
        self.table_name = table_name


def test_recall_fields_full_library_direct_inject_below_threshold(monkeypatch):
    """无 schema 提问 + 全库字段总数 < 阈值 → 直接整库直通（不经向量/关键词召回）"""
    retriever = _make_retriever()
    rows = [_FakeRow('sakila', 'film_category'), _FakeRow('sakila', 'film'),
            _FakeRow('falcon_dev_14', 'toy_sales'), _FakeRow('falcon_dev_14', 'toy_sales')]
    monkeypatch.setattr(retriever, 'field_count', lambda sn=None: 300)
    monkeypatch.setattr(retriever, 'get_field_rows',
                        lambda sn=None, tn=None, scope=None: rows)
    monkeypatch.setattr('core.ret_retriever.get_vector_config',
                        lambda key: 500 if key == 'VECTOR_INDEX_THRESHOLD' else 50)

    def _must_not_touch_vector(*a, **kw):
        raise AssertionError('字段数低于阈值时不应触碰向量索引')
    monkeypatch.setattr(retriever, 'try_load_vector_store', _must_not_touch_vector)

    out = retriever.recall_fields(['任意'], schema_name=None, query='q')
    assert all(d.get('full_scope') and d.get('recall_source') == 'full' for d in out)
    # 同库同名表去重，占位带库名
    assert [(d['schema_name'], d['table_name']) for d in out] == [
        ('sakila', 'film_category'), ('sakila', 'film'),
        ('falcon_dev_14', 'toy_sales')]


def test_recall_fields_vector_path_when_total_fields_reach_threshold(monkeypatch):
    """全库字段总数达到阈值 → 不直通，走向量召回（现有行为不回归）"""
    retriever = _make_retriever()
    retriever.vector_loaded = True
    vec = [{'schema_name': 'DM', 'table_name': 'DM_KEY_ACTUAL_INDICATOR_DATA',
            'column_name': 'ACCOUNT', 'recall_source': 'vector'}]
    monkeypatch.setattr(retriever, 'field_count', lambda sn=None: 721)
    monkeypatch.setattr(retriever, 'search_vector', lambda *a, **kw: list(vec))
    monkeypatch.setattr(retriever, '_filter_recalled_by_permission',
                        lambda res, sn=None, scope=None: res)
    monkeypatch.setattr(retriever, 'recall_from_db', lambda kws, sn=None, scope=None: [])
    monkeypatch.setattr('core.ret_retriever.get_vector_config',
                        lambda key: 500 if key == 'VECTOR_INDEX_THRESHOLD' else 50)

    out = retriever.recall_fields(['科目'], schema_name=None, query='费用合计科目')
    assert [d['column_name'] for d in out] == ['ACCOUNT']
    assert all(not d.get('full_scope') for d in out)


# ---------- 3/4. 追问轮：判断 prompt 注入自动召回知识 + 知识表进 keep_first ----------

class _FakeLLM:
    """记录 judge prompt，返回不可生成以短路在判断步"""

    def __init__(self):
        self.judge_prompt = None

    def call_llm_json(self, prompt):
        self.judge_prompt = prompt
        return {'can_generate': False, 'reason': 'test', 'suggestion': 'test-sugg'}

    def chat(self, messages):   # 判断步放行时才会走到；测试不应到达
        raise AssertionError('测试不应进入生成步')


class _FakeSqlGen:
    """记录判断 prompt 的构造入参"""

    def __init__(self):
        self.judge_kwargs = None

    def judge_generatable_prompt(self, **kwargs):
        self.judge_kwargs = kwargs
        return 'JUDGE-PROMPT'


class _FakeRetriever:
    """召回层全 mock：记录 aggregate_tables 的 keep_first 与 recalled 标记"""

    vector_loaded = True       # gen_chat 追问分支探测用（跳过向量懒加载）
    vector_error = None

    def __init__(self):
        self.agg_calls = []

    def recall_fields(self, keywords, schema_name=None, query=None, scope=None):
        return [{'schema_name': 'ODS', 'table_name': 'ODS_FILL_RD_MIANBODY_INFO',
                 'column_name': 'VALUE', 'recall_source': 'vector'}]

    def aggregate_tables(self, recalled_fields, schema_name=None, keep_first=None,
                         scope=None):
        tables = list(dict.fromkeys(
            f['table_name'] for f in recalled_fields if f.get('table_name')))
        all_fields = {}
        for t in tables:
            if t.startswith('DM_KEY_'):
                # 知识扩表：完整列结构（含度量列），验证白名单不得裁掉
                for col in ('ACCOUNT', 'ACCOUNT_NAME', 'ACTUAL_VALUE',
                            'ENTITY', 'ENTITY_NAME', 'PROJECT_LINE',
                            'PROJECT_LINE_NAME', 'PERIODS', 'YEARS'):
                    all_fields[f'DM.{t}.{col}'] = {
                        'schema_name': 'DM', 'table_name': t,
                        'column_name': col, 'column_type': 'varchar(64)',
                        'column_description': '', 'column_key': '',
                        'foreign_key': ''}
        self.agg_calls.append({'tables': tables, 'keep_first': keep_first,
                               'recalled': recalled_fields})
        return {'tables': tables, 'all_fields': all_fields,
                'schema_name': schema_name}

    def recall_knowledge(self, query, scope_schema_id=None,
                         keywords=None, exclude_contents=None, scope=None):
        return {'items': [{'id': 14, 'title': '口语词到科目编码映射',
                           'knowledge_type': 'entity_map', 'aliases': ['费用'],
                           'content': ENTITY_MAP_TEXT,
                           'payload': {'related_tables': DM_FACT_TABLES}}],
                'prompt_text': ENTITY_MAP_TEXT,
                'related_tables': DM_FACT_TABLES}

    def resolve_scope_schema_id(self, schema_name):
        return None

    def get_relations_text(self, tables, max_relations=30, scope=None):
        return ''


def test_followup_judge_gets_knowledge_and_keep_first(monkeypatch):
    """追问轮：①判断 prompt 必须并入自动召回知识；②知识扩表进 keep_first 防裁剪；
    ③知识扩表的列全部进字段白名单（度量列不得被裁）"""
    from core.gen_chat import ChatSession
    from core.ret_retriever import SchemaRetriever

    llm, sql_gen = _FakeLLM(), _FakeSqlGen()
    session = ChatSession(user_id=1, llm_client=llm, sql_generator=sql_gen,
                          user={'user_id': 1, 'role': 'admin'})
    retriever = _FakeRetriever()
    session.retriever = retriever
    monkeypatch.setattr('core.gen_chat.write_query_audit_log',
                        lambda *a, **kw: 1)

    # 捕获 build_schema_csv 的白名单入参（第三层回归点）
    real_build_csv = SchemaRetriever.build_schema_csv
    csv_calls = []

    def spy_build_csv(aggregation, whitelist=None):
        csv_calls.append({'aggregation': aggregation, 'whitelist': whitelist})
        return real_build_csv(aggregation, whitelist)

    monkeypatch.setattr('core.gen_chat.SchemaRetriever.build_schema_csv',
                        spy_build_csv)

    first_junk = [f'ODS_JUNK_{i}' for i in range(10)]   # 首轮 10 张杂表（占满名额）
    result = session.process_followup_message(
        conversation_messages=[],
        new_user_content='24-09公司费用合计科目值是多少',
        schema_csv='表名,字段名,字段类型\nODS_JUNK_0,VALUE,varchar',
        first_tables=first_junk,
        db_type='mysql',
        schema_name=None,
        knowledge_content='',          # 用户未勾选任何知识库（复现 conv8 场景）
    )

    # ③ 判断步拿到了含 entity_map 的自动召回知识（此前只有用户勾选知识）
    kb = sql_gen.judge_kwargs['knowledge_content']
    assert 'AA0003' in kb and 'EETotal' in kb

    # ④ 知识扩表进入 keep_first（与首轮杂表同级"必留"待遇）
    assert len(retriever.agg_calls) == 2
    second = retriever.agg_calls[1]
    keep = second['keep_first'] or set()
    for t in DM_FACT_TABLES:
        assert t in keep, f'{t} 应入 keep_first，防止被 MAX_TABLES 裁掉'
    # 知识表带 recall_source='knowledge' 标记（聚合权重 5 > DB 兜底 1）
    marked = {f['table_name'] for f in second['recalled']
              if f.get('recall_source') == 'knowledge'}
    assert marked == set(DM_FACT_TABLES)

    # ⑤ 知识表的列全部进字段白名单——度量列 ACTUAL_VALUE 不得被裁
    assert csv_calls, 'build_schema_csv 应被调用'
    whitelist = csv_calls[-1]['whitelist'] or set()
    dm_cols = {c for (t, c) in whitelist
               if t == 'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC'}
    assert 'ACTUAL_VALUE' in dm_cols, '知识表度量列被字段白名单裁掉'
    assert {'ACCOUNT', 'ENTITY', 'PROJECT_LINE', 'PERIODS', 'YEARS'} <= dm_cols

    # 判断步按 mock 返回不可生成 → 走 need_more_info 短路，链路完整
    assert result['need_more_info'] is True
    assert result['error_message'] == 'test-sugg'


# ---------- 5. seed 脚本声明 related_tables ----------

def test_seed_specs_declare_dm_fact_tables():
    """两条 DM 知识必须声明 related_tables=4 张事实表（脚本即数据源真相）"""
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        'seed_knowledge_under_test', root / 'scripts' / 'seed_knowledge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    by_title = {e['title']: e for e in module.KNOWLEDGE_ENTRIES}
    for title in ('DM 事实表选择：实际数/预算数 × 明细/指标卡',
                  '口语词到科目编码/维度字段映射（DM）'):
        assert by_title[title]['related_tables'] == module.DM_FACT_TABLES
    assert 'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC' in module.DM_FACT_TABLES


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
