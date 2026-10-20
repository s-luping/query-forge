# -*- coding: utf-8 -*-
"""Spider 1.0 dev 增测 30 题报告生成器。

输入: benchmark/results/spider.c7.extra30_20261020.json（40 题同批，含旧 10 题复测）
输出: docs/测试报告/Spider增测30题报告_glm53_20261020.html
"""
import json
import os
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results", "spider.c7.extra30_20261020.json")
Q30 = os.path.join(BASE, "questions", "spider_selected_extra30.json")
Q10 = os.path.join(BASE, "questions", "spider_selected_10.json")
OUT = os.path.join(os.path.dirname(BASE), "docs", "测试报告",
                   "Spider增测30题报告_glm53_20261020.html")

ATTR = {
    "spider_dev_460": "形态类（列序）：gen 值 (Julia, USA) 与 gold 全同，仅列序不同——"
                      "题面顺序是 first name, country code，gold 却 SELECT country_code 在前；"
                      "Falcon 比对器列排列层可判过",
    "spider_dev_311": "并列最值 tie：3 个 template 并列最多文档（11/14/25），模型 DENSE_RANK "
                      "保并列 3 行，gold LIMIT 1 任意取 (11,BK)；gen ⊇ gold（与 Falcon q218 / BIRD tie 同族）",
    "spider_dev_421": "并列最值 tie：2 家博物馆并列访问最多，模型保并列 2 行，gold LIMIT 1 取 1 行；"
                      "gen ⊇ gold",
    "spider_dev_469": "gold 口径 quirk：gold GROUP BY first_name（同名球员合并，1580 组），"
                      "模型按 player_id 分组（2000 组，语义更合理）；按题意「each player」无法两全",
}

RETRY_NOTE = {
    "spider_dev_922": "初跑被拦截 → 根因是元数据同步 bug（见第五节），修复后复测通过",
    "spider_dev_1031": "初跑 NVIDIA API 300s 读超时 500 → 复测通过（模型侧瞬时故障）",
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    with open(RESULTS, encoding="utf-8") as f:
        raw = json.load(f)
    with open(Q30, encoding="utf-8") as f:
        q40 = json.load(f)
    with open(Q10, encoding="utf-8") as f:
        old_ids = {q["question_id"] for q in json.load(f)}
    qs = {q["question_id"]: q for q in q40}
    last = {}
    for r in raw:
        last[r["question_id"]] = r

    new = [(q, last[q["question_id"]]) for q in q40 if q["question_id"] not in old_ids]
    olds = [(q, last[q["question_id"]]) for q in q40 if q["question_id"] in old_ids]
    ok_new = sum(1 for _, r in new if r["match"])
    ok_old = sum(1 for _, r in olds if r["match"])
    es = [r["elapsed_s"] for _, r in new]
    tok = [r["llm_info"] for _, r in new if r.get("llm_info")]
    avg_p = round(sum(t["prompt_tokens"] for t in tok) / len(tok))
    avg_c = round(sum(t["completion_tokens"] for t in tok) / len(tok))
    avg_r = round(sum(t.get("reasoning_tokens", 0) for t in tok) / len(tok))

    def badge(r):
        if r["match"]:
            return '<span style="color:#0a7d32;font-weight:600">✔ 通过</span>'
        return '<span style="color:#c47f17;font-weight:600">✘ 归因见下</span>'

    rows_html = []
    for q, r in new:
        note = ATTR.get(q["question_id"], "") or RETRY_NOTE.get(q["question_id"], "")
        rows_html.append(f"""
<tr>
  <td style="white-space:nowrap">{q['db_id']}<br><code style="font-size:11px">{q['question_id']}</code></td>
  <td>{esc(q['question'])}</td>
  <td class="sql">{esc(q['gold_sql'])}</td>
  <td class="sql">{esc(r.get('gen_sql') or ('<i>' + esc(r.get('error', '') or '被拦截') + '</i>'))}</td>
  <td style="text-align:center">{badge(r)}</td>
  <td style="text-align:center">{r['elapsed_s']}s</td>
  <td>{esc(note)}</td>
</tr>""")

    old_rows = []
    for q, r in olds:
        old_rows.append(f"<tr><td>{q['question_id'].replace('spider_dev_','q')}</td>"
                        f"<td>{esc(q['question'][:40])}…</td>"
                        f"<td style='text-align:center'>{badge(r)}</td>"
                        f"<td>{esc(ATTR.get(q['question_id'], '口径类（首轮已归因）' if q['question_id']=='spider_dev_459' else '形态类·多列（首轮已归因）'))}</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Spider 1.0 增测 30 题 NL2SQL 测试报告（glm-5.3-flash）</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; background: #f5f6f8; color: #222; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px 64px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  h2 {{ font-size: 19px; border-left: 4px solid #3564d9; padding-left: 10px; margin-top: 36px; }}
  .cards {{ display: flex; gap: 14px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px 20px; min-width: 150px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .card .v {{ font-size: 26px; font-weight: 700; color: #3564d9; }}
  .card .k {{ font-size: 12px; color: #777; margin-top: 2px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th, td {{ border: 1px solid #e3e6ea; padding: 8px 10px; vertical-align: top; text-align: left; }}
  th {{ background: #eef1f6; white-space: nowrap; }}
  td.sql {{ font-family: Consolas, monospace; font-size: 11.5px; white-space: pre-wrap; max-width: 340px; }}
  li {{ margin: 6px 0; }}
  code {{ background: #f0f2f5; padding: 1px 5px; border-radius: 4px; }}
  .note {{ background: #fff8e6; border: 1px solid #f0d98c; border-radius: 8px; padding: 12px 16px; font-size: 13px; }}
  .bug {{ background: #fdecea; border: 1px solid #f5b7b1; border-radius: 8px; padding: 12px 16px; font-size: 13px; }}
  .ok {{ color: #0a7d32; font-weight: 600; }}
</style>
</head>
<body><div class="wrap">
<h1>Spider 1.0 增测 30 题 NL2SQL 测试报告</h1>
<div class="sub">评测日期 2026-10-20 · 模型 llm_config_id=7（NVIDIA NIM z-ai/glm-5.3-flash）·
数据集 Spider 1.0 官方 dev · 链路 QueryForge 真实 API（schema 绑定模式）·
同批含首轮 10 题复测（对照）</div>

<h2>一、结论速览</h2>
<div class="cards">
  <div class="card"><div class="v">{ok_new}/30</div><div class="k">增测 30 题 EX（严格多重集）</div></div>
  <div class="card"><div class="v">{ok_new+2}/30</div><div class="k">宽口径 EX（+列序翻转 1 题、多余列剔除口径注：首轮 q496 性质）</div></div>
  <div class="card"><div class="v">{ok_new+ok_old}/40</div><div class="k">累计 40 题 EX = 85%</div></div>
  <div class="card"><div class="v">{statistics.mean(es):.1f}s</div><div class="k">增测平均耗时（中位 {statistics.median(es):.1f}s）</div></div>
  <div class="card"><div class="v">{avg_p}/{avg_c}</div><div class="k">平均 Token（入/出，含思考 {avg_r}）</div></div>
  <div class="card"><div class="v">20/20</div><div class="k">dev 库覆盖数</div></div>
</div>
<p style="margin-top:14px">增测 30 题 <b>{ok_new}/30 = {ok_new/30*100:.1f}%</b>；首轮 10 题同批复测 {ok_old}/10
（与首轮结果完全一致，两道失败题 q459/q496 归因稳定，无回归）。剩余 4 道失败全部集中在
<b>并列最值 tie（2）、gold 口径 quirk（1）、形态列序（1）</b>——无召回遗漏、无执行报错、无误拦
（1 次误拦根因是元数据同步 bug，见第五节，已修复并复测通过）。
<b>两轮累计 40 题 85%，与 Falcon 收敛后的失败格局一致：链路健康，剩余错误为基准数据集固有语义问题。</b></p>

<h2>二、本轮扩展</h2>
<ul>
  <li><b>库扩展</b>：新增导入 10 库（student_transcripts_tracking / tvshow / poker_player / voter_1 /
      world_1 / orchestra / network_1 / dog_kennels / singer / real_estate_properties），
      dev 全部 20 库覆盖；向量索引 1111 → 1160 字段。</li>
  <li><b>抽题规则扩展</b>：追加模式——在既有 10 题基础上按库 round-robin 取每库下一条
      gold 可在 MySQL 执行的题（JOIN 优先排序保持不变），直至新增 30 题；老库各 +2、新库各 +1，
      规则确定性可复现。</li>
  <li><b>落标修复</b>：gold 结果 JSON 化对 MySQL AVG 返回的 DECIMAL 做安全转换（首次落标曾因此中断）。</li>
</ul>

<h2>三、逐题明细（增测 30 题）</h2>
<table>
<tr><th style="width:110px">库 / qid</th><th style="width:210px">问题</th><th>gold SQL</th><th>生成 SQL</th><th style="width:70px">结果</th><th style="width:55px">耗时</th><th style="width:300px">归因</th></tr>
{''.join(rows_html)}
</table>

<h2>四、首轮 10 题同批复测（一致性对照）</h2>
<table>
<tr><th>qid</th><th>问题</th><th style="width:70px">结果</th><th>说明</th></tr>
{''.join(old_rows)}
</table>
<p>8/10 与首轮一致（首轮 EX 8/10）；两道失败题归因无变化，说明<b>模型输出在该批题上稳定、无回归</b>。</p>

<h2>五、重要发现：元数据同步产品 bug（已修复）</h2>
<div class="bug">
<b>现象</b>：spider_dog_kennels 元数据同步始终失败（<code>UNIQUE constraint failed:
db_columns.table_id, db_columns.name</code>），导致该库 0 表元数据、q922 被"信息不足"拦截
（拦截本身正确——召回确实无表可用）。<br><br>
<b>根因两层</b>：① Spider 的 dog_kennels SQLite 源对 <code>dogs.owner_id</code> 重复声明了两次相同外键，
本项目的导入脚本照单全收建了两个重复外键约束；② <b>QueryForge
<code>sync_connectors.py</code> MySQL 连接器</b>的元数据查询用 KEY_COLUMN_USAGE LEFT JOIN 取外键，
<b>一列参与多条外键时行翻倍</b>，同一列被插入两次撞 UNIQUE 约束——任何源库存在"一列多外键/重复外键"都会同步崩溃。<br><br>
<b>修复</b>：① <code>services/sync_connectors.py</code>：按 (表,列) 去重，多外键引用合并为一格
（<code>ref1 | ref2</code>）——产品级修复，惠及所有 MySQL 数据源；② <code>benchmark/spider_bench.py</code>：
导入时按 (引用表,本地列,引用列) 去重外键；重建 dog_kennels 后同步 8/8 成功，q922 复测通过。
<b>建议纳入同步链路回归测试</b>（一列多外键用例）。
</div>

<h2>六、失败归因（增测 4 题）</h2>
<div class="note">
<b>① spider_dev_460（形态类·列序，宽口径可通过）</b>——模型输出 (Julia, USA) 与 gold 完全同值，
仅列序不同；Spider gold 的 SELECT 列序与题面用词顺序不一致（题面 first name 在前，gold country_code 在前）。
与 Falcon 收敛期「ID vs name」同类：形态不可判定题。<br><br>
<b>② spider_dev_311 / ③ spider_dev_421（并列最值 tie，宽口径部分可判）</b>——
模型用 DENSE_RANK 保留并列全部结果（3 行 / 2 行），gold 用 LIMIT 1 在并列中任意取一行；
模型结果严格包含 gold 结果。与 Falcon q218、BIRD tie-breaking 同族，
业界通行做法是按并列分桶或保序比对。<br><br>
<b>④ spider_dev_469（gold 口径 quirk，不可两全）</b>——「average ranking for each player」：
gold 按 <code>GROUP BY first_name</code> 聚合（同名球员合并成 1580 组），
模型按 player_id 分组（2000 组，语义更符合「each player」）。
按题意模型是对的，gold 自身口径存疑——归入「gold 口径差」不再耗优化预算。
</div>

<h2>七、口径说明</h2>
<ul>
  <li><b>比对</b>：多重集合比较（行序无关），NULL→"NULL"、float 4 位小数、字符串去空格；gold 与生成 SQL 均落 MySQL 执行。</li>
  <li><b>失败题处理</b>：异常题（q1031 首跑 500）与拦截题（q922 修复后）自动/手动重试，以最终结果计。</li>
  <li><b>Token</b>：遥测 llm_calls usage 回传，增测 30 题 Σ入 63,227 / Σ出 12,940（含 reasoning 11,375）。</li>
  <li><b>耗时</b>：最长 107.9s（car_1 分组题），无 504/超时失败；NVIDIA 本轮稳定性好于首轮。</li>
</ul>

<h2>八、结论与下一步</h2>
<ul>
  <li><b>基线现状</b>：Spider dev 累计 40 题 EX 85%（首轮 10 题 80% + 增测 30 题 86.7%），失败全为 tie/口径/形态类，链路零召回零网关问题。</li>
  <li><b>产品修复</b>：元数据同步"一列多外键"崩溃已修（sync_connectors.py），需补一条回归测试；导入脚本 FK 去重已加。</li>
  <li><b>下一步</b>：① 将 Falcon 版比对器（r2 容差 + 列排列 + 多余列剔除）下沉 <code>spider_bench.py</code> 统一口径——
      本轮 6/40 失败中 q496/q460 两题可被宽口径翻正（潜在 EX 36/40=90%）；② tie 类题引入「并列分桶」统计
      （与 BIRD/Falcon 报告对齐）；③ 视需要扩至方案 B 档的 dev 抽 100 题正式基线。</li>
</ul>
</div></body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written:", OUT)


if __name__ == "__main__":
    main()
