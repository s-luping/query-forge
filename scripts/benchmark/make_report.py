# -*- coding: utf-8 -*-
"""读取 qf_results.json 生成 BIRD 基准测试 HTML 报告。"""
import html
import json
from collections import Counter

SRC = r"D:\qf_bench\qf_results.json"
OUT = r"d:\projects\query-forge\docs\BIRD基准NL2SQL测试报告.html"

with open(SRC, encoding="utf-8") as f:
    rs = json.load(f)

total = len(rs)
n_ok = sum(1 for r in rs if r["match"])
by_db = Counter(r["db_id"] for r in rs)
by_diff = Counter(r["difficulty"] for r in rs)
ok_by_db = Counter(r["db_id"] for r in rs if r["match"])
ok_by_diff = Counter(r["difficulty"] for r in rs if r["match"])
avg_t = sum(r["elapsed_s"] for r in rs) / max(total, 1)
fail = [r for r in rs if not r["match"]]


def esc(s):
    return html.escape(str(s if s is not None else ""))


rows_html = []
for i, r in enumerate(rs):
    badge = ('<span class="ok">通过</span>' if r["match"]
             else '<span class="no">不通过</span>')
    note = ""
    if r.get("need_more_info"):
        note = "拦截: " + esc(r.get("missing_info") or r.get("suggestion"))
    elif r.get("exec_error"):
        note = "执行错误: " + esc(r["exec_error"])
    elif not r["match"]:
        note = "结果不一致"
    if r.get("error"):
        note = "请求异常: " + esc(r["error"])
    rows_html.append(f"""
<tr>
 <td>{i+1}</td><td>{esc(r['db_id'])}</td><td>{esc(r['difficulty'])}</td>
 <td class="q">{esc(r['question'])}</td>
 <td class="q">{esc(r.get('gen_sql')) or '-'}</td>
 <td>{r.get('gold_rows_count')} / {r.get('gen_rows_count', '-')}</td>
 <td>{badge}</td><td class="q">{note}</td><td>{r['elapsed_s']}s</td>
</tr>""")

db_rows = "".join(
    f"<tr><td>{esc(db)}</td><td>{ok_by_db.get(db,0)}/{by_db[db]}</td></tr>"
    for db in ["bird_superhero", "bird_formula_1", "bird_financial"])
diff_rows = "".join(
    f"<tr><td>{esc(d)}</td><td>{ok_by_diff.get(d,0)}/{by_diff[d]}</td></tr>"
    for d in ["simple", "moderate", "challenging"])

doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>BIRD 基准 NL2SQL 测试报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.sum{{display:flex;gap:16px;margin:16px 0}}
.card{{background:#f6f8fa;border-radius:8px;padding:14px 20px;text-align:center;flex:1}}
.card b{{font-size:26px;display:block}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}
.q{{max-width:340px;word-break:break-all;font-family:Consolas,monospace;font-size:12px}}
.ok{{color:#1a7f37;font-weight:bold}} .no{{color:#cf222e;font-weight:bold}}
.evi{{color:#57606a;font-size:12px}}
</style></head><body>
<h1>QueryForge NL2SQL — BIRD 基准测试报告</h1>
<p>数据集: BIRD dev (2024-06-27 官方 OSS 版) · 测试库: superhero / formula_1 / financial
(SQLite→MySQL 8.0 迁移，含官方列描述注释) · LLM: doubao-seed-2-1-pro-260628 (id=4) ·
评测方式: 执行准确率(结果集多重集比对，浮点 4 位舍入)</p>
<div class="sum">
 <div class="card"><b>{n_ok}/{total}</b>执行准确率</div>
 <div class="card"><b>{avg_t:.0f}s</b>平均耗时/题</div>
 <div class="card"><b>{total - len([r for r in rs if r.get('exec_error') or r.get('error')])}</b>SQL 成功执行</div>
</div>
<h2>分库结果</h2><table><tr><th>数据库</th><th>通过</th></tr>{db_rows}</table>
<h2>分难度结果</h2><table><tr><th>难度</th><th>通过</th></tr>{diff_rows}</table>
<h2>明细</h2>
<table><tr><th>#</th><th>库</th><th>难度</th><th>问题</th><th>QF 生成 SQL</th>
<th>行数(gold/gen)</th><th>结论</th><th>说明</th><th>耗时</th></tr>
{''.join(rows_html)}
</table>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)
print("report ->", OUT)
