# -*- coding: UTF-8 -*-
"""P1 留痕统一（StepTrace）回归 — docs/07-ChatSQL模块化与全链路留痕设计.md §5.2

覆盖：
1. StepTracker：字段完整性 / 耗时单调 / 显式 duration 覆盖
2. ChatSession._log_step：新结构追加（不再产出旧格式 {step,timestamp,data}）
3. process_first_message / process_followup_message 全链路：
   每步必有 status/duration_ms/summary/error，judged 拦截步 status='intercept'
4. _repair_missing_schema_prefix 的 info 留痕（见 test_prefix_repair.py 扩展用例）
"""
import pytest

from core.gen_audit import StepTracker
from core.gen_chat import ChatSession

STEPTRACE_KEYS = {'step', 'status', 'started_at', 'duration_ms',
                  'summary', 'detail', 'error'}


# ---------- 1. StepTracker 单元 ----------

def test_steptracker_entry_fields_and_monotonic_duration():
    steps = []
    t = StepTracker()
    t.add(steps, 'STEP_A', data={'x': 1})
    import time as _time
    _time.sleep(0.02)
    t.add(steps, 'STEP_B', data={'y': 2})
    assert [s['step'] for s in steps] == ['STEP_A', 'STEP_B']
    for s in steps:
        assert STEPTRACE_KEYS <= set(s.keys())
        assert s['status'] == 'ok'
        assert s['error'] is None
        assert isinstance(s['duration_ms'], int) and s['duration_ms'] >= 0
        assert s['detail'] and s['detail'] != {}
    assert steps[1]['duration_ms'] >= steps[0]['duration_ms']
    assert steps[0]['summary'] == ''


def test_steptracker_explicit_duration_override():
    steps = []
    StepTracker().add(steps, 'SQL_EXECUTE', data={}, duration_ms=1234)
    assert steps[0]['duration_ms'] == 1234


def test_steptracker_status_and_error_passthrough():
    steps = []
    StepTracker().add(steps, 'STEP_X', data={'e': 1}, status='intercept',
                      error='信息不足')
    assert steps[0]['status'] == 'intercept'
    assert steps[0]['error'] == '信息不足'


# ---------- 2. ChatSession._log_step ----------

def _make_session():
    """构造 ChatSession（llm/gen 为假对象，仅测 _log_step 与全链路留痕）"""
    return ChatSession(user_id=1, llm_client=_FakeLLM(), sql_generator=_FakeSqlGen(),
                       user={'user_id': 1, 'role': 'admin'})


def test_log_step_appends_steptrace_not_legacy_format():
    s = _make_session()
    steps = []
    s._log_step(steps, 'STEP1_KEYWORDS', {'count': 2}, summary='2 个关键词')
    assert len(steps) == 1
    e = steps[0]
    assert STEPTRACE_KEYS <= set(e.keys())
    assert 'data' not in e and 'timestamp' not in e, '不得再产出旧格式字段'
    assert e['detail'] == {'count': 2}
    assert e['summary'] == '2 个关键词'


# ---------- 3. 全链路（首轮 + 追问，假 LLM/召回） ----------

class _FakeLLM:
    def call_llm_json(self, prompt):
        return {'can_generate': False, 'reason': '缺金额字段',
                'missing_info': ['金额'], 'suggestion': '请补充金额口径'}

    def chat(self, messages):
        return {'sql': 'SELECT 1', 'raw_response': 'SELECT 1',
                'prompt_tokens': 1, 'completion_tokens': 1,
                'reasoning_tokens': 0, 'total_tokens': 2}


class _FakeSqlGen:
    def judge_generatable_prompt(self, **kw):
        return 'JUDGE_PROMPT'

    def validate_sql(self, sql):
        return True, None, ['col1']


class _FakeRetriever:
    vector_loaded = True

    def recall_fields(self, keywords, schema_name=None, query=None, scope=None):
        return [{'schema_name': 'db1', 'table_name': 't1', 'column_name': 'c1'}]

    def aggregate_tables(self, recalled_fields, schema_name=None, keep_first=None,
                         scope=None):
        return {'tables': ['t1'],
                'all_fields': {'db1.t1.c1': {'schema_name': 'db1', 'table_name': 't1',
                                             'column_name': 'c1'}}}

    def recall_knowledge(self, query, scope_schema_id=None, keywords=None,
                         exclude_contents=None, scope=None,
                         preferred_schema_ids=None):
        return {'items': [], 'prompt_text': '', 'related_tables': []}

    def recall_tables_by_name(self, keywords, schema_name=None, scope=None):
        return []

    def schema_ids_by_names(self, names):
        return []

    def resolve_scope_schema_id(self, schema_name):
        return None

    def get_relations_text(self, tables, max_relations=30, scope=None):
        return ''

    def extend_aggregation_with_tables(self, aggregation, tables, schema_name,
                                       scope=None):
        return aggregation


def test_first_message_pipeline_all_steps_have_steptrace(monkeypatch):
    """首轮全链路：每步都有 StepTrace 字段；判断拦截步 status='intercept' 且 error 非空"""
    s = _make_session()
    s.retriever = _FakeRetriever()
    monkeypatch.setattr('core.gen_chat.write_query_audit_log', lambda *a, **kw: 1)
    result = s.process_first_message(query='测试问题', db_type='mysql')
    log = result['pipeline_log']
    assert log, 'pipeline_log 不能为空'
    for e in log:
        assert STEPTRACE_KEYS <= set(e.keys()), f'{e.get("step")} 缺 StepTrace 字段: {e.keys()}'
        assert e['status'] in ('ok', 'error', 'intercept', 'skip')
        assert isinstance(e['duration_ms'], int) and e['duration_ms'] >= 0
    steps = [e['step'] for e in log]
    # 前置步骤为空时从 PIPELINE_START 开始，拦截在判断步短路
    assert 'PIPELINE_START' in steps and 'STEP_JUDGE_RESULT' in steps
    judge = next(e for e in log if e['step'] == 'STEP_JUDGE_RESULT')
    assert judge['status'] == 'intercept'
    assert judge['error'] == '缺金额字段'
    assert result['need_more_info'] is True


def test_followup_no_keywords_marks_skip_steps(monkeypatch):
    """追问无关键词：STEP2_RECALL/STEP3_AGGREGATE 按 skip 留痕（不再伪装成正常召回）"""
    s = _make_session()
    s.retriever = _FakeRetriever()
    monkeypatch.setattr('core.gen_chat.write_query_audit_log', lambda *a, **kw: 1)
    result = s.process_followup_message(
        conversation_messages=[], new_user_content='不对',
        schema_csv='表名,字段名\nA,B', first_tables=['t1'], db_type='mysql')
    by_step = {e['step']: e for e in result['pipeline_log']}
    assert by_step['STEP2_RECALL']['status'] == 'skip'
    assert by_step['STEP3_AGGREGATE']['status'] == 'skip'


def test_followup_generation_path_steptrace_complete(monkeypatch):
    """追问正常生成路径：LLM 生成/校验/网关步均落 StepTrace"""
    class _PassLLM(_FakeLLM):
        def call_llm_json(self, prompt):
            return {'can_generate': True, 'reason': ''}

    s = _make_session()
    s.llm_client = _PassLLM()
    s.retriever = _FakeRetriever()
    monkeypatch.setattr('core.gen_chat.write_query_audit_log', lambda *a, **kw: 1)
    result = s.process_followup_message(
        conversation_messages=[], new_user_content='销量合计是多少',
        schema_csv='表名,字段名\nA,B', first_tables=['t1'], db_type='mysql')
    log = result['pipeline_log']
    for e in log:
        assert STEPTRACE_KEYS <= set(e.keys()), f'{e.get("step")} 缺 StepTrace 字段'
    steps = [e['step'] for e in log]
    assert 'STEP5_RESULT' in steps
    gen = next(e for e in log if e['step'] == 'STEP5_RESULT')
    assert gen['status'] == 'ok'
    assert 'SELECT 1' in gen['detail']['sql']


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
