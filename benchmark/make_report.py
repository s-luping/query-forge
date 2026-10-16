# -*- coding: utf-8 -*-
"""生成 BIRD 基准测试 HTML 报告。

用法:
  python make_report.py <主模型结果.json> "<主模型标签>" [输出.html]
对照固定使用历史 bird_eval_turbo.json（doubao-seed-2-1-turbo）结果，不重跑。
"""
import json
import sys
import html
from collections import Counter

RESULTS = r"D:\projects\query-forge\benchmark\results"
COMP = RESULTS + r"\bird_eval_turbo.json"
COMP_LABEL = "doubao-seed-2-1-turbo (id=5)"

MAIN = sys.argv[1] if len(sys.argv) > 1 else RESULTS + r"\bird_eval_nvidia_glm53.json"
MAIN_LABEL = sys.argv[2] if len(sys.argv) > 2 else "nvidia glm-5.3-flash (id=7)"
OUT = sys.argv[3] if len(sys.argv) > 3 else r"d:\projects\query-forge\docs\BIRD基准NL2SQL测试报告.html"


def load_dedup(path):
    with open(path, encoding="utf-8") as f:
        rs = json.load(f)
    last = {}
    for r in rs:
        last[r["question_id"]] = r
    return list(last.values())


def stats(rs):
    return dict(
        total=len(rs),
        ok=sum(1 for r in rs if r["match"]),
        err=sum(1 for r in rs if r.get("error")),
        blocked=sum(1 for r in rs if r.get("need_more_info") and not r.get("error")),
        valid=sum(1 for r in rs if not r.get("error")),
        avg_t=sum(r["elapsed_s"] for r in rs) / max(len(rs), 1),
    )


main = load_dedup(MAIN)
comp = load_dedup(COMP)
st, sc = stats(main), stats(comp)
comp_by_qid = {r["question_id"]: r for r in comp}

by_db = Counter(r["db_id"] for r in main)
by_diff = Counter(r["difficulty"] for r in main)
ok_by_db = Counter(r["db_id"] for r in main if r["match"])
ok_by_diff = Counter(r["difficulty"] for r in main if r["match"])
executed = sum(1 for r in main if not r.get("error") and not r.get("need_more_info"))


def esc_html(s):
    return html.escape(str(s if s is not None else ""))


rows_html = []
for i, r in enumerate(sorted(main, key=lambda x: (x["db_id"], x["difficulty"]))):
    if r.get("error"):
        badge = '<span class="er">请求异常</span>'
        note = "异常: " + esc_html(r.get("error"))
    elif r.get("need_more_info"):
        badge = '<span class="nb">拦截</span>'
        note = "信息不足: " + esc_html(r.get("missing_info") or r.get("suggestion"))
    elif r["match"]:
        badge = '<span class="ok">通过</span>'
        note = ""
    else:
        badge = '<span class="no">不通过</span>'
        note = "执行成功但结果不一致" if not r.get("exec_error") else "执行错误: " + esc_html(r.get("exec_error"))
    c = comp_by_qid.get(r["question_id"])
    comp_txt = "-" if not c else ("通过" if c["match"] else ("拦截" if c.get("need_more_info") else "不通过"))
    rows_html.append(f"""
<tr>
 <td>{i+1}</td><td>{esc_html(r['db_id'])}</td><td>{esc_html(r['difficulty'])}</td>
 <td class="q">{esc_html(r['question'])}</td>
 <td class="q">{esc_html(r.get('gen_sql')) or '-'}</td>
 <td>{r.get('gold_rows_count')} / {r.get('gen_rows_count', '-')}</td>
 <td>{badge}</td><td class="q">{esc_html(note)}</td>
 <td>{comp_txt}</td><td>{r['elapsed_s']}s</td>
</tr>""")

db_rows = "".join(
    f"<tr><td>{esc_html(db)}</td><td>{ok_by_db.get(db,0)}/{by_db[db]}</td></tr>"
    for db in ["bird_superhero", "bird_formula_1", "bird_financial"])
diff_rows = "".join(
    f"<tr><td>{esc_html(d)}</td><td>{ok_by_diff.get(d,0)}/{by_diff[d]}</td></tr>"
    for d in ["simple", "moderate", "challenging"])

acc = f"{st['ok']}/{st['valid']}"
pct = st["ok"] / max(st['valid'], 1) * 100

doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>BIRD 基准 NL2SQL 测试报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1240px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.sum{{display:flex;gap:16px;margin:16px 0}}
.card{{background:#f6f8fa;border-radius:8px;padding:14px 20px;text-align:center;flex:1}}
.card b{{font-size:26px;display:block}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}
.q{{max-width:340px;word-break:break-all;font-family:Consolas,monospace;font-size:12px}}
.ok{{color:#1a7f37;font-weight:bold}} .no{{color:#cf222e;font-weight:bold}}
.nb{{color:#9a6700;font-weight:bold}} .er{{color:#8250df;font-weight:bold}}
</style></head><body>
<h1>QueryForge NL2SQL — BIRD 基准测试报告（{esc_html(MAIN_LABEL)}）</h1>
<p><b>数据集:</b> BIRD dev（2024-06-27 官方发布，阿里云 OSS 直下，1534 题/11 库）·
<b>测试库:</b> superhero(10 表) / formula_1(13 表) / financial(8 表)，SQLite→MySQL 8.0 迁移，
保留主键/外键，官方 database_description 列说明写入 MySQL COMMENT ·
<b>选题:</b> 24 题（各库 simple×3 / moderate×3 / challenging×2，gold SQL 可在 MySQL 执行）·
<b>评测:</b> 执行准确率（生成 SQL 与 gold SQL 在 MySQL 上执行结果多重集比对，浮点 4 位舍入）</p>
<div class="sum">
 <div class="card"><b>{acc} ({pct:.0f}%)</b>执行准确率(有效题)</div>
 <div class="card"><b>{st['blocked']}</b>拦截(信息不足)</div>
 <div class="card"><b>{executed}</b>SQL 成功执行</div>
 <div class="card"><b>{st['avg_t']:.0f}s</b>平均耗时/题</div>
</div>
<p><b>主模型:</b> {esc_html(MAIN_LABEL)}（NVIDIA NIM 免费额度，base_url=integrate.api.nvidia.com/v1，OpenAI 兼容协议）。
历史对照: {esc_html(COMP_LABEL)} 在同题集上 {sc['ok']}/{sc['valid']} 通过
（{sc['ok']/max(sc['valid'],1)*100:.0f}%），对照结果取自历史评测存档，未重跑。</p>
<h2>分库结果（{esc_html(MAIN_LABEL)}）</h2><table><tr><th>数据库</th><th>通过/总题</th></tr>{db_rows}</table>
<h2>分难度结果（{esc_html(MAIN_LABEL)}）</h2><table><tr><th>难度</th><th>通过/总题</th></tr>{diff_rows}</table>
<h2>明细（{esc_html(MAIN_LABEL)}，末列为 {esc_html(COMP_LABEL)} 对照）</h2>
<table><tr><th>#</th><th>库</th><th>难度</th><th>问题</th><th>QF 生成 SQL</th>
<th>行数(gold/gen)</th><th>结论</th><th>说明</th><th>对照</th><th>耗时</th></tr>
{''.join(rows_html)}
</table>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)
print("report ->", OUT)
