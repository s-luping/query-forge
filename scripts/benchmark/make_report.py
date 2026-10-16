# -*- coding: utf-8 -*-
"""读取 qf_results_turbo.json（主）/ qf_results.json（pro 对照），生成 BIRD 基准测试 HTML 报告。"""
import json
import html
from collections import Counter

TURBO = r"D:\qf_bench\qf_results_turbo.json"
PRO = r"D:\qf_bench\qf_results.json"
OUT = r"d:\projects\query-forge\docs\BIRD基准NL2SQL测试报告.html"


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


turbo = load_dedup(TURBO)
pro = load_dedup(PRO)
st, sp = stats(turbo), stats(pro)

by_db = Counter(r["db_id"] for r in turbo)
by_diff = Counter(r["difficulty"] for r in turbo)
ok_by_db = Counter(r["db_id"] for r in turbo if r["match"])
ok_by_diff = Counter(r["difficulty"] for r in turbo if r["match"])
executed = sum(1 for r in turbo if not r.get("error") and not r.get("need_more_info"))


def esc_html(s):
    return html.escape(str(s if s is not None else ""))


rows_html = []
for i, r in enumerate(sorted(turbo, key=lambda x: (x["db_id"], x["difficulty"]))):
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
    rows_html.append(f"""
<tr>
 <td>{i+1}</td><td>{esc_html(r['db_id'])}</td><td>{esc_html(r['difficulty'])}</td>
 <td class="q">{esc_html(r['question'])}</td>
 <td class="q">{esc_html(r.get('gen_sql')) or '-'}</td>
 <td>{r.get('gold_rows_count')} / {r.get('gen_rows_count', '-')}</td>
 <td>{badge}</td><td class="q">{esc_html(note)}</td><td>{r['elapsed_s']}s</td>
</tr>""")

db_rows = "".join(
    f"<tr><td>{esc_html(db)}</td><td>{ok_by_db.get(db,0)}/{by_db[db]}</td></tr>"
    for db in ["bird_superhero", "bird_formula_1", "bird_financial"])
diff_rows = "".join(
    f"<tr><td>{esc_html(d)}</td><td>{ok_by_diff.get(d,0)}/{by_diff[d]}</td></tr>"
    for d in ["simple", "moderate", "challenging"])

acc = f"{st['ok']}/{st['valid']}"
pct = st["ok"] / max(st["valid"], 1) * 100

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
<h1>QueryForge NL2SQL — BIRD 基准测试报告</h1>
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
<p><b>主模型:</b> doubao-seed-2-1-turbo-260628 (id=5)。
对照: doubao-seed-2-1-pro-260628 (id=4) 在 17 道有效题上 {sp['ok']}/{sp['valid']} 通过
（{sp['ok']/max(sp['valid'],1)*100:.0f}%），pro 于测试中途方舟配额耗尽服务暂停，未完成全量。
turbo 轮在最后 4 题同样触发配额上限（SetLimitExceeded），如需补全需在火山方舟控制台提额。</p>
<h2>分库结果（turbo）</h2><table><tr><th>数据库</th><th>通过/总题</th></tr>{db_rows}</table>
<h2>分难度结果（turbo）</h2><table><tr><th>难度</th><th>通过/总题</th></tr>{diff_rows}</table>
<h2>明细（turbo）</h2>
<table><tr><th>#</th><th>库</th><th>难度</th><th>问题</th><th>QF 生成 SQL</th>
<th>行数(gold/gen)</th><th>结论</th><th>说明</th><th>耗时</th></tr>
{''.join(rows_html)}
</table>
<h2>过程发现的问题</h2>
<ul>
<li><b>已修复缺陷:</b> 创建对话接口在响应序列化阶段引用了 <code>request.schema_name</code>（应为
<code>payload.schema_name</code>），导致每轮首轮生成在全部成功后仍返回 500，前端拿不到 SQL 与结果。
已修复 app/routers/conversation_router.py 并经本轮验证。</li>
<li><b>已知问题 1:</b> 同步任务 run 状态恒为 failed——元数据同步实际成功（表/列全部入库），
但收尾阶段抛 <code>DbSchema not bound to Session</code>，建议排查 services/sync_engine.py 会话管理。</li>
<li><b>已知问题 2:</b> 信息不足拦截（5 题）集中在 need_more_info 分支，其中 formula_1 challenging
3 题全部拦截，复杂多表链路的字段召回有提升空间。</li>
<li><b>已知问题 3:</b> 火山方舟账号 doubao 系列模型配额耗尽（pro 与 turbo 先后被暂停），
影响长基准测试连续性。</li>
</ul>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)
print("report ->", OUT)
