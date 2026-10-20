# -*- coding: utf-8 -*-
"""Spider 1.0 dev 累计 140 题报告生成器。

输入: benchmark/results/spider.cumulative_140.analysis.json（analyze_spider.py 产出）
输出: docs/测试报告/Spider累计140题报告_glm53_20261020.html
"""
import json
import os
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.join(BASE, "..", "results", "spider", "spider.cumulative_140.analysis.json")
OUT = os.path.join(os.path.dirname(os.path.dirname(BASE)), "docs", "测试报告",
                   "Spider累计140题报告_glm53_20261020.html")

ATTR = {
    "spider_dev_459": "口径类：gold 按 rankings 单行 tours DESC LIMIT 1（SQLite 弱语义），模型按 "
                      "SUM(tours) 聚合，胜者不同（不可两全）",
    "spider_dev_469": "gold quirk：gold GROUP BY first_name（同名球员合并 1580 组），模型按 "
                      "player_id 分组（2000 组）——按题意「each player」模型是对的",
    "spider_dev_471": "同 q469：gold GROUP BY first_name vs 模型按 player_id（口径差，不可两全）",
    "spider_dev_500": "gold quirk：题面「most total injuries」应为 SUM(injured)，gold 用 count(*) "
                      "计死亡行数，两者选出不同船",
    "spider_dev_610": "枚举照抄偏差：题面「The Rise of the Blue Beetle!」带感叹号，模型生成 SQL 丢"
                      "「!」→ 0 行（枚举值需逐字符照抄）",
    "spider_dev_923": "方言错误：HAVING 引用非聚合列 p.state（SQLite 允许，MySQL 报 1054），"
                      "应把 state 条件放入 WHERE",
    "spider_dev_95": "gold quirk + tie：horsepower 为 TEXT 列，gold ORDER BY 字典序 LIMIT 1；"
                     "模型 CAST 数值排序并保并列 6 行（数值语义下模型对）",
    "spider_dev_96": "同 q95：TEXT 列字典序 vs 数值排序 + 并列保留（6 行 vs 1 行）",
    "spider_dev_698": "口径差 + tie：gold 用 area_code_state 映射表 JOIN，模型 SUBSTR(phone_number) "
                      "推导区号，且并列保序 4 行 vs gold LIMIT 1",
    "spider_dev_687": "gold quirk：area_code_state 表含重复 state 行，gold count(*)=19 按行数，"
                      "模型 COUNT(DISTINCT state) 按州数——按题意模型对",
    "spider_dev_1033": "枚举幻觉：实际枚举值 'House'/'Apartment'，模型写了 Spider 训练集惯例的 "
                       "'Hse'/'Apt' → 0 行（方向与常见幻觉相反）",
    "spider_dev_526": "边界口径：题面「less than 2」，gold HAVING count(*)<=2（含 2），模型 <2"
                      "（7 行 vs 11 行）——gold 自身口径存疑",
}
BUCKET_LABEL = {
    "tie_superset": "并列保序",
    "wide_pass": "形态类（宽口径过）",
    "true_wrong": "真错（含 gold quirk）",
    "exec_error": "执行错误（方言）",
}
TIE_NOTE = "并列最值/并列计数：模型 DENSE_RANK/RANK 保留全部并列行（gen ⊇ gold），gold LIMIT 1 任意取一行"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    with open(ANALYSIS, encoding="utf-8") as f:
        rows = json.load(f)
    n = len(rows)
    ok = sum(1 for r in rows if r["bucket"] == "ok")
    wide = sum(1 for r in rows if r["bucket"] in ("ok", "wide_pass"))
    buckets = Counter(r["bucket"] for r in rows)
    by_db = defaultdict(lambda: [0, 0])
    for r in rows:
        by_db[r["db_id"]][1] += 1
        if r["bucket"] == "ok":
            by_db[r["db_id"]][0] += 1
    avg_e = sum(r["elapsed_s"] for r in rows) / n
    fails = [r for r in rows if r["bucket"] != "ok"]
    by_db_fail = Counter(r["db_id"] for r in fails)

    db_rows = "".join(
        f"<tr><td>{d}</td><td style='text-align:center'>{v[0]}/{v[1]}</td>"
        f"<td>{by_db_fail.get(d, 0)}</td></tr>"
        for d, v in sorted(by_db.items()))

    fail_rows = []
    for r in sorted(fails, key=lambda x: (x["bucket"], x["dev_index"])):
        note = ATTR.get(r["question_id"], "")
        if r["bucket"] == "tie_superset":
            note = TIE_NOTE
        b = BUCKET_LABEL.get(r["bucket"], r["bucket"])
        fail_rows.append(f"""
<tr><td style="white-space:nowrap">{r['db_id']}<br><code style="font-size:11px">{r['question_id']}</code></td>
<td style="width:90px">{b}</td><td>{esc(r['question'][:120])}</td>
<td class="sql">{esc((r['gen_sql'] or '<i>{}</i>'.format(esc(r.get('error') or r.get('exec_error') or '被拦截')))[:400])}</td>
<td class="sql">{esc(r['gold_sql'][:400])}</td>
<td>{esc(note)}</td></tr>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Spider 1.0 累计 140 题 NL2SQL 测试报告（glm-5.3-flash）</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; background: #f5f6f8; color: #222; }}
  .wrap {{ max-width: 1240px; margin: 0 auto; padding: 32px 24px 64px; }}
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
  td.sql {{ font-family: Consolas, monospace; font-size: 11.5px; white-space: pre-wrap; max-width: 320px; }}
  li {{ margin: 6px 0; }}
  code {{ background: #f0f2f5; padding: 1px 5px; border-radius: 4px; }}
  .note {{ background: #fff8e6; border: 1px solid #f0d98c; border-radius: 8px; padding: 12px 16px; font-size: 13px; }}
</style>
</head>
<body><div class="wrap">
<h1>Spider 1.0 累计 140 题 NL2SQL 测试报告</h1>
<div class="sub">评测日期 2026-10-20 · 模型 llm_config_id=7（NVIDIA NIM z-ai/glm-5.3-flash）·
Spider 1.0 官方 dev 抽样（20 库全覆盖，固定规则可复现）· 统一口径离线重算（gen SQL 全量重放 + 分层比对）</div>

<h2>一、结论速览</h2>
<div class="cards">
  <div class="card"><div class="v">{ok}/{n}</div><div class="k">执行准确率 EX（严格多重集）= {ok/n*100:.1f}%</div></div>
  <div class="card"><div class="v">{wide}/{n}</div><div class="k">宽口径 EX（列序/多余列/容差）= {wide/n*100:.1f}%</div></div>
  <div class="card"><div class="v">{buckets['tie_superset']}</div><div class="k">并列保序（gen ⊇ gold，另计）</div></div>
  <div class="card"><div class="v">{buckets['true_wrong'] + buckets['exec_error']}</div><div class="k">真错（含 gold quirk 与方言错误）</div></div>
  <div class="card"><div class="v">{avg_e:.1f}s</div><div class="k">平均端到端耗时</div></div>
  <div class="card"><div class="v">20/20</div><div class="k">库覆盖 · 0 拦截误伤 · 0 召回遗漏</div></div>
</div>
<p style="margin-top:14px">三轮累计（抽样 10 → 增测 30 → 增测 100）共 <b>{n}</b> 题，统一以最新一轮作答离线重算。
严格 EX <b>{ok/n*100:.1f}%</b>；加列序翻转/多余列剔除/数值容差后 <b>{wide/n*100:.1f}%</b>；
另有 {buckets['tie_superset']} 题模型结果严格包含 gold（并列最值 gold 任意取一行）。真错 {buckets['true_wrong'] + buckets['exec_error']} 题
中约半数为 <b>gold 口径 quirk</b>（TEXT 字典序、count(*) 代 SUM、GROUP BY first_name、边界 &lt;=2 等），
模型侧可改进项集中在：<b>枚举值逐字符照抄</b>（q610 丢「!」、q1033 写错枚举方向）与 <b>MySQL 方言 HAVING 限制</b>（q923）。
无拦截误伤、无召回遗漏、无网关问题——链路健康，失败格局与 Falcon 收敛后一致。</p>

<h2>二、分库统计</h2>
<table>
<tr><th>库</th><th style="width:110px">EX（严格/题数）</th><th style="width:110px">失败题数</th></tr>
{db_rows}
</table>

<h2>三、失败题明细（{len(fails)} 题）</h2>
<table>
<tr><th style="width:110px">库 / qid</th><th style="width:95px">分桶</th><th style="width:200px">问题</th><th>生成 SQL</th><th>gold SQL</th><th style="width:280px">归因</th></tr>
{''.join(fail_rows)}
</table>

<h2>四、失败分桶说明</h2>
<ul>
  <li><b>并列保序（{buckets['tie_superset']} 题）</b>：{TIE_NOTE}。模型结果 ⊇ gold，
      建议评测时「并列分桶」单独统计（BIRD/Falcon 同款 tie-breaking 问题），不耗优化预算。</li>
  <li><b>形态类（{buckets['wide_pass']} 题，宽口径通过）</b>：列序与题面用词不一致（perm 层）、
      多输出 1 列（extra_col 层）、AVG 半进位 0.0001 级精度漂移（tol 层 ±0.0015）。</li>
  <li><b>gold quirk（true_wrong 内约 6 题）</b>：TEXT 列字典序排序、count(*) 代 SUM、
      GROUP BY first_name、边界 &lt;=2、行数代州数——gold 自身口径与题面语义不符，不可两全。</li>
  <li><b>模型侧可改进（2 类）</b>：① <b>枚举值照抄</b>——q610 丢「!」、q1033 写 'Hse'/'Apt'
      而实际是 'House'/'Apartment'（Spider 训练集先验反噬），沉淀「枚举值逐字符照抄实际值」知识条目；
      ② <b>方言</b>——q923 HAVING 非聚合列，MySQL 不允许，生成 prompt 已有方言提示可再强化「聚合条件放 WHERE/HAVING 的边界」。</li>
</ul>

<h2>五、口径与工具链</h2>
<ul>
  <li><b>统一比对器</b>（<code>spider_bench.wide_compare</code>，对齐 Falcon 收敛版）：
      ① r3/ci 精确多重集 → ② 数值容差（字符串锚点分组配对，±0.0015，吸收 AVG 半进位漂移）→
      ③ 列排列（≤3 列放宽到 2000 行）→ ④ 排列+容差 → ⑤ 多余列剔除（gen 列 = gold+1）。</li>
  <li><b>离线重算</b>（<code>analyze_spider.py</code>）：三轮结果按 qid 取最新，gen SQL 全量重放 MySQL，
      统一 strict/wide/分桶；重放含 Decimal→float 安全转换（MySQL AVG 返回 DECIMAL）。</li>
  <li><b>多线程</b>：<code>spider_bench test</code> 已支持 <code>workers</code> 并发 +
      <code>fallback_ids</code> 配置链（单题超时/5xx 按序换配置重试）；本轮 4 道异常题 80 秒并发重试完成
      （2 题翻正）。配置链 = [7] + 用户新增的 9/10/8。</li>
  <li>新增 LLM 配置（id=9 minimax-m3.1-flash、id=10 mimo-v2.6-pro，腾讯 tokenhub）已接入并验证可用；
      按用户指示未重跑模型对比。</li>
</ul>

<h2>六、结论与下一步</h2>
<ul>
  <li><b>基线定格</b>：Spider dev 累计 140 题严格 EX 80.0% / 宽口径 85.0%，与 Falcon 收敛后（74.0% 严格）
      同一量级、同一失败格局——两套基准互证链路稳定性。</li>
  <li><b>近期可做</b>：① 知识库补「枚举值逐字符照抄」与「MySQL HAVING 非聚合列」条目，小批复测
      （q610/1033/923 三题为目标）；② tie 分桶纳入报告口径；③ 新模型（id=9/10）待用户指示后跑同题集对比。</li>
</ul>
</div></body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written:", OUT)


if __name__ == "__main__":
    main()
