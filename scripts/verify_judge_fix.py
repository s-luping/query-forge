# -*- coding: UTF-8 -*-
"""一次性集成验证（非启服）：conv8「24-09费用合计」修复后，判断步的输入是否补齐

复现事故场景的两条路径，用真实召回 + 真实知识库（不 mock 数据库）：
  A. 首轮路径：新对话问「24-09公司费用合计科目值是多少」
  B. 追问路径：复现 conv8（首轮 10 张杂表 + 用户未勾选知识）发最后一轮追问

两条路径都只跑到判断步：用假 LLM 在 call_llm_json 处短路（返回不可生成），
捕获真实 SqlGenerator 构造的 judge prompt，检查：
  1. schema_csv 是否包含 DM_KEY_ACTUAL_INDICATOR_DATA_METRIC（表覆盖）
  2. knowledge_content 是否包含 AA0003 / EETotal / PJTotal（口径覆盖）
  3. 用真实 LLM 对捕获的 judge prompt 发起一次真实判断调用，看 can_generate

用法：.venv\\Scripts\\python.exe scripts\\verify_judge_fix.py [--llm]
"""
import argparse
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.routers.conversation_router import _build_llm_client  # noqa: E402
from core.gen_chat import ChatSession  # noqa: E402
from core.gen_sql import SqlGenerator  # noqa: E402

QUERY = '24-09公司费用合计科目值是多少'
FOLLOWUP_QUERY = '科目AA0003开头合计 EETotal PJTotal'
FIRST_JUNK_TABLES = [
    'ODS_FILL_RD_MIANBODY_INFO', 'ODS_FILL_DAILY_REPORT_DETAILS',
    'ODS_FILL_PRODUCTLINE_ENTITY_INFO_XMJJ', 'ODS_FILL_PRODUCTLINE_INFO',
    'ODS_COMPLETE_PAY_VALUE', 'ODS_WEEK_QUARTERLY_REVENUE', 'ODS_ISSUE_LEVEL1',
    'ODS_DAILY_REPORT_DETAILS_bak', 'ODS_PAY_COMPLETED', 'DIM_BUDGET_HYPLN_ACCOUNT',
]


class _ShortCircuitLLM:
    """判断步短路：记录 prompt，返回不可生成（阻止进入生成步）"""

    def __init__(self):
        self.judge_prompt = None

    def call_llm_json(self, prompt):
        self.judge_prompt = prompt
        return {'can_generate': False, 'reason': 'short-circuit', 'suggestion': 'x'}

    def chat(self, messages):
        raise AssertionError('不应进入生成步')


def _spy_judge(session: ChatSession, store: dict):
    """包装 sql_generator.judge_generatable_prompt：透传真实实现 + 记录入参"""
    real = SqlGenerator.judge_generatable_prompt

    def spy(self, **kwargs):
        prompt = real(self, **kwargs)
        store['kwargs'] = kwargs
        store['prompt'] = prompt
        return prompt

    session.sql_generator.judge_generatable_prompt = types.MethodType(
        spy, session.sql_generator)


def _check(label: str, store: dict):
    kw = store['kwargs']
    schema_csv = kw.get('schema_csv') or ''
    kb = kw.get('knowledge_content') or ''
    checks = {
        'schema_csv 含 DM_KEY_ACTUAL_INDICATOR_DATA_METRIC':
            'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC' in schema_csv,
        'schema_csv 含 ACTUAL_VALUE 字段': 'ACTUAL_VALUE' in schema_csv,
        'kb 含 AA0003（费用合计）': 'AA0003' in kb,
        'kb 含 EETotal（公司汇总）': 'EETotal' in kb,
        'kb 含 PJTotal（项目汇总）': 'PJTotal' in kb,
    }
    print(f'\n===== {label} =====')
    print(f'schema_csv 行数: {len(schema_csv.splitlines())}，'
          f'kb 长度: {len(kb)}')
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return all(checks.values()), store.get('prompt', '')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--llm', action='store_true',
                        help='对捕获的 judge prompt 发起真实 LLM 判断调用')
    args = parser.parse_args()

    user = {'user_id': 1, 'role': 'admin'}

    # ── A. 首轮路径 ──
    store_a = {}
    llm_a = _ShortCircuitLLM()
    session_a = ChatSession(user_id=1, llm_client=llm_a,
                            sql_generator=SqlGenerator(), user=user)
    _spy_judge(session_a, store_a)
    session_a.process_first_message(query=QUERY, schema_name=None,
                                    db_type='mysql')
    ok_a, prompt_a = _check('A. 首轮（新对话直接提问）', store_a)

    # ── B. 追问路径（复现 conv8：首轮杂表 + 未勾选知识）──
    store_b = {}
    llm_b = _ShortCircuitLLM()
    session_b = ChatSession(user_id=1, llm_client=llm_b,
                            sql_generator=SqlGenerator(), user=user)
    _spy_judge(session_b, store_b)
    session_b.process_followup_message(
        conversation_messages=[],
        new_user_content=FOLLOWUP_QUERY,
        schema_csv='表名,字段名,字段类型\nODS_JUNK,VALUE,varchar',
        first_tables=FIRST_JUNK_TABLES,
        db_type='mysql',
        schema_name=None,
        knowledge_content='',
    )
    ok_b, prompt_b = _check('B. 追问（conv8 场景复现，空历史）', store_b)

    # ── C. 追问路径（conv8 真实历史：含"24-09就是期间"等口径确立轮）──
    import sqlite3
    conn = sqlite3.connect(str(ROOT / 'db' / 'queryforge.db'))
    conn.row_factory = sqlite3.Row
    history = [dict(r) for r in conn.execute(
        "SELECT role, content, sql FROM conversation_messages "
        "WHERE conversation_id=8 ORDER BY id").fetchall()]
    conn.close()
    store_c = {}
    llm_c = _ShortCircuitLLM()
    session_c = ChatSession(user_id=1, llm_client=llm_c,
                            sql_generator=SqlGenerator(), user=user)
    _spy_judge(session_c, store_c)
    session_c.process_followup_message(
        conversation_messages=history,
        new_user_content='科目AA0003开头合计 EETotal PJTotal',
        schema_csv='表名,字段名,字段类型\nODS_JUNK,VALUE,varchar',
        first_tables=FIRST_JUNK_TABLES,
        db_type='mysql',
        schema_name=None,
        knowledge_content='',
    )
    ok_c, prompt_c = _check('C. 追问（conv8 真实历史）', store_c)

    print('\n汇总: A(首轮)=', 'PASS' if ok_a else 'FAIL',
          ' B(追问,空历史)=', 'PASS' if ok_b else 'FAIL',
          ' C(追问,真实历史)=', 'PASS' if ok_c else 'FAIL')

    if args.llm:
        client = _build_llm_client(1)
        print(f'\n===== 真实 LLM 判断调用（model={client.model}）=====')
        for label, prompt in (('A.首轮', prompt_a), ('B.追问(空历史)', prompt_b),
                              ('C.追问(真实历史)', prompt_c)):
            try:
                verdict = client.call_llm_json(prompt)
                print(f'{label}: can_generate='
                      f'{verdict.get("can_generate")} | '
                      f'reason={(verdict.get("reason") or "")[:200]}')
            except Exception as e:
                print(f'{label}: [ERR] {e}')
    return 0 if (ok_a and ok_b and ok_c) else 1


if __name__ == '__main__':
    sys.exit(main())
