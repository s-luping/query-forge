# -*- coding: UTF-8 -*-
"""追问轮 aggregation=None 回归测试

背景（conv11 事故）：追问文本分词后无有效业务关键词（或向量召回异常降级）时
`aggregation` 保持 None，但 `first_tables` 非空仍会进入累积合并分支——
gen_chat.py 曾在此处直接 `aggregation.get('tables')`，触发
`AttributeError: 'NoneType' object has no attribute 'get'`，POST /messages 500。
"""
import pytest

from core.gen_chat import ChatSession


class _Stop(Exception):
    """哨兵异常：到达 LLM 调用即截停（证明流程已越过原崩溃点）"""


class _StubRetriever:
    """SchemaRetriever 桩：记录 aggregate_tables 调用参数供断言"""

    vector_loaded = False

    def __init__(self, recall_fields=None, knowledge_tables=None):
        # recall_fields 传 Exception 实例 = 模拟召回抛错（降级路径）
        self._recall_fields = recall_fields if recall_fields is not None else []
        self._knowledge_tables = knowledge_tables or []
        self.aggregate_calls = []

    def recall_fields(self, keywords, schema_name, query=None):
        if isinstance(self._recall_fields, Exception):
            raise self._recall_fields
        return self._recall_fields

    def aggregate_tables(self, recalled_fields, schema_name=None, keep_first=None):
        self.aggregate_calls.append({
            'recalled': list(recalled_fields),
            'schema_name': schema_name,
            'keep_first': keep_first,
        })
        tables = [f['table_name'] for f in recalled_fields if f.get('table_name')]
        return {'tables': tables, 'all_fields': {}, 'schema_name': schema_name,
                'full_scope': False}

    def recall_knowledge(self, query, scope_schema_id=None, exclude_contents=None,
                         keywords=None):
        return {'items': [], 'prompt_text': '',
                'related_tables': list(self._knowledge_tables)}

    def resolve_scope_schema_id(self, schema_name):
        return None

    def get_relations_text(self, table_names, max_relations=30):
        return ''


class _StubKeywordExtractor:
    def __init__(self, keywords):
        self._keywords = keywords

    def extract(self, text, top_k=10):
        return list(self._keywords)


class _StubSqlGenerator:
    def judge_generatable_prompt(self, **kwargs):
        return 'judge-prompt'

    def validate_sql(self, sql):
        return True, '', []


class _StubLLMClient:
    def __init__(self):
        self.chat_called = False

    def call_llm_json(self, prompt):
        return {'can_generate': True}

    def chat(self, messages):
        self.chat_called = True
        raise _Stop()


def _make_session(retriever, keywords):
    """绕过 __init__（避免真实 DB/向量初始化），直接装配桩依赖"""
    session = ChatSession.__new__(ChatSession)
    session.user_id = 1
    session.user = {'user_id': 1, 'role': 'admin'}
    session.keyword_extractor = _StubKeywordExtractor(keywords)
    session.retriever = retriever
    session.sql_generator = _StubSqlGenerator()
    session.llm_client = _StubLLMClient()
    return session


# 历史消息：assistant 消息的 SQL 用到 subject_ledger + account_subject 两表
HISTORY = [
    {'role': 'user', 'content': '26年9月的一级科目总金额', 'sql': None},
    {'role': 'assistant', 'content': 'SELECT ...',
     'sql': ('SELECT a.subject_name, SUM(t.amount) AS total '
             'FROM DM.subject_ledger t JOIN DM.account_subject a '
             'ON t.subject_id = a.id GROUP BY a.subject_name')},
]

SCHEMA_CSV = ('表名,字段名,字段类型,字段描述,主键,外键\n'
              'subject_ledger,id,bigint,,PRI,\n')


def test_followup_no_keywords_first_tables_present():
    """事故路径1：追问无有效关键词 → aggregation=None，first_tables 非空不得 500"""
    retriever = _StubRetriever(knowledge_tables=['account_subject'])
    session = _make_session(retriever, keywords=[])
    with pytest.raises(_Stop):
        session.process_followup_message(
            conversation_messages=HISTORY,
            new_user_content='26年9月',
            schema_csv=SCHEMA_CSV,
            first_tables=['subject_ledger', 'account_subject'],
            db_type='mysql', schema_name='DM')
    assert session.llm_client.chat_called
    # 复用上一轮上下文：合并集 = 历史 SQL 用过的表 + 知识扩表
    merged = retriever.aggregate_calls[-1]
    assert merged['keep_first'] == {'subject_ledger', 'account_subject'}
    merged_tables = [i['table_name'] for i in merged['recalled']]
    assert 'account_subject' in merged_tables


def test_followup_recall_degraded_first_tables_present():
    """事故路径2：召回异常降级 → aggregation=None，同样不得 500"""
    retriever = _StubRetriever(recall_fields=RuntimeError('vector boom'))
    session = _make_session(retriever, keywords=['一级', '科目'])
    with pytest.raises(_Stop):
        session.process_followup_message(
            conversation_messages=HISTORY,
            new_user_content='一级科目总金额',
            schema_csv=SCHEMA_CSV,
            first_tables=['subject_ledger'],
            db_type='mysql', schema_name='DM')
    assert session.llm_client.chat_called


def test_followup_normal_merge_order_unchanged():
    """正常路径回归：历史 SQL 表在前，召回表/知识扩表按序并入且不重复"""
    retriever = _StubRetriever(
        recall_fields=[{'table_name': 'voucher_detail', 'column_name': 'amount'}],
        knowledge_tables=['account_subject'])
    session = _make_session(retriever, keywords=['一级', '科目', '总金额'])
    with pytest.raises(_Stop):
        session.process_followup_message(
            conversation_messages=HISTORY,
            new_user_content='26年9月的一级科目总金额',
            schema_csv=SCHEMA_CSV,
            first_tables=['subject_ledger'],
            db_type='mysql', schema_name='DM')
    assert session.llm_client.chat_called
    merged = retriever.aggregate_calls[-1]
    # subject_ledger/account_subject 来自历史 SQL（在前且保序）；
    # voucher_detail 本轮召回（追加在后）；知识扩表 account_subject 已存在不重复
    merged_tables = [i['table_name'] for i in merged['recalled']]
    assert merged_tables == ['subject_ledger', 'account_subject', 'voucher_detail']
    # 必留集 = 历史 SQL 用过的表 ∪ 知识扩表
    assert merged['keep_first'] == {'subject_ledger', 'account_subject'}
