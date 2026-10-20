# -*- coding: utf-8 -*-
"""Spider 1.0 dev 抽样 10 题报告生成器。

输入: benchmark/results/spider.c7.selected10_20261020.json + benchmark/questions/spider_selected_10.json
输出: docs/测试报告/Spider抽样10题报告_glm53_20261020.html
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results", "spider.c7.selected10_20261020.json")
QUESTIONS = os.path.join(BASE, "questions", "spider_selected_10.json")
OUT = os.path.join(os.path.dirname(BASE), "docs", "测试报告",
                   "Spider抽样10题报告_glm53_20261020.html")

ATTR = {
    "spider_dev_22": "",
    "spider_dev_51": "",
    "spider_dev_89": "",
    "spider_dev_207": "",
    "spider_dev_277": "",
    "spider_dev_307": "",
    "spider_dev_399": "",
    "spider_dev_419": "",
    "spider_dev_459": "口径类：gold 按 rankings 单行 tours DESC 取首个匹配行（SQLite 弱语义），"
                      "模型按 SUM(tours) 聚合后取最大——两者胜者不同（GRE/Eleni vs USA/Julia）；"
                      "首跑 NVIDIA glm-5.3-flash 思考 300s 超时 504，重试完成",
    "spider_dev_496": "纯形态类：生成 SQL 多输出未要求的 note 列（killed, injured, note vs gold "
                      "killed, injured）；剔除多余列后 11 行完全一致，Falcon 宽口径（多余列剔除）下判过",
}

CLS = {
    "spider_dev_459": ("口径差", "#c47f17"),
    "spider_dev_496": ("形态类", "#c47f17"),
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    with open(RESULTS, encoding="utf-8") as f:
        raw = json.load(f)
    with open(QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)
    last = {}
    for r in raw:
        last[r["question_id"]] = r
    qs = {q["question_id"]: q for q in questions}

    n = len(last)
    ok = sum(1 for r in last.values() if r["match"])
    avg_e = sum(r["elapsed_s"] for r in last.values()) / n
    tok = [r["llm_info"] for r in last.values() if r.get("llm_info")]
    avg_p = round(sum(t["prompt_tokens"] for t in tok) / len(tok))
    avg_c = round(sum(t["completion_tokens"] for t in tok) / len(tok))
    avg_r = round(sum(t.get("reasoning_tokens", 0) for t in tok) / len(tok))
    sum_p = sum(t["prompt_tokens"] for t in tok)
    sum_c = sum(t["completion_tokens"] for t in tok)

    rows_html = []
    for q in questions:
        r = last[q["question_id"]]
        if r["match"]:
            badge = '<span style="color:#0a7d32;font-weight:600">✔ 通过</span>'
        else:
            label, color = CLS.get(q["question_id"], ("失败", "#b3261e"))
            badge = f'<span style="color:{color};font-weight:600">✘ {label}</span>'
        rows_html.append(f"""
<tr>
  <td style="white-space:nowrap">{q['db_id']}<br><code style="font-size:11px">{q['question_id']}</code></td>
  <td>{esc(q['question'])}</td>
  <td class="sql">{esc(q['gold_sql'])}</td>
  <td class="sql">{esc(r.get('gen_sql') or ('<i>' + esc(r.get('error', '')) + '</i>'))}</td>
  <td style="text-align:center">{badge}</td>
  <td style="text-align:center">{r['elapsed_s']}s</td>
  <td>{esc(ATTR.get(q['question_id'], ''))}</td>
</tr>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Spider 1.0 抽样 10 题 NL2SQL 测试报告（glm-5.3-flash）</title>
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
  .ok {{ color: #0a7d32; font-weight: 600; }}
</style>
</head>
<body><div class="wrap">
<h1>Spider 1.0 抽样 10 题 NL2SQL 测试报告</h1>
<div class="sub">评测日期 2026-10-20 · 模型 llm_config_id=7（NVIDIA NIM z-ai/glm-5.3-flash）·
数据集 Spider 1.0 官方 dev（1034 题 / 20 库，来源 ModelScope ModelM/spider 官方包）·
链路 QueryForge 真实 API（schema 绑定模式）</div>

<h2>一、结论速览</h2>
<div class="cards">
  <div class="card"><div class="v">{ok}/{n}</div><div class="k">执行准确率 EX（严格多重集）</div></div>
  <div class="card"><div class="v">{ok+1}/{n}</div><div class="k">宽口径 EX（Falcon 多余列剔除）</div></div>
  <div class="card"><div class="v">{avg_e:.1f}s</div><div class="k">平均端到端耗时（含 1 次 504 重试）</div></div>
  <div class="card"><div class="v">{avg_p}/{avg_c}</div><div class="k">平均 Token（入/出，含思考 {avg_r}）</div></div>
  <div class="card"><div class="v">10/10</div><div class="k">gold SQL MySQL 可执行率</div></div>
</div>
<p style="margin-top:14px">8 题一次通过与标准答案完全一致（含 7 题多表 JOIN / 分组聚合）；2 题失败，
1 题为<b>形态类</b>（多加未要求列，剔除后结果全等，宽口径判过）、1 题为<b>口径类</b>
（gold 依赖 SQLite 弱语义单行取 max，与聚合语义不可两全）。无召回遗漏、无拦截、无执行报错、无限流——
<b>失败模式与 Falcon 收敛后的格局一致：剩余错误集中在 gold 口径/结果形态，召回与生成链路本身没有暴露新问题。</b></p>

<h2>二、数据集接入</h2>
<ul>
  <li><b>数据源</b>：Spider 1.0 官方包（spider.zip 99.7MB + dev.json + dev_gold.sql + tables.json），
      ModelScope <code>ModelM/spider</code> 国内直连约 1 分钟；GitHub/HF 官方渠道均不可直连或缺库文件。</li>
  <li><b>导入</b>：10 个 dev 库 → 本地 MySQL <code>spider_&lt;db_id&gt;</code>
      （concert_singer / pets_1 / car_1 / flight_2 / employee_hire_evaluation / cre_doc_template_mgt /
      course_teach / museum_visit / wta_1 / battle_death，最大 wta_1 rankings 51 万行）。</li>
  <li><b>导入修复的 3 个坑</b>（脚本 <code>benchmark/spider_bench.py</code>，可复用于全量接入）：
    ① SQLite 无类型声明列做主/外键时 TEXT 不可索引 → 键列映射 VARCHAR(255)；
    ② Spider gold schema 外键两端类型常不一致（如 concert.Stadium_ID text 引用 int 列）→ 本地列类型跟随被引用列；
    ③ 被引用的非主键列（model_list.Model）MySQL 建外键时必须已有索引 → 建表 DDL 内联建索引；
    另：BIGINT 列的空串脏值（wta_1 rankings.player_id=''）批量转 NULL。</li>
  <li><b>QueryForge 接入</b>：10 个数据源（id 24~33）+ 全量同步任务 + 向量索引重建
      （721 → 909 字段，BGE-M3，全部 success）。</li>
  <li><b>抽题规则（固定可复现）</b>：按 dev.json 库首现顺序逐库取第一条 gold SQL 可在 MySQL 执行的题，
      优先选含 JOIN 的题（鉴别召回/关联能力），无 JOIN 可执行题时回退第一条；每库 1 题，共 10 题。
      gold 结果集在导入库上离线执行落标。</li>
</ul>

<h2>三、逐题明细</h2>
<table>
<tr><th style="width:110px">库 / qid</th><th style="width:200px">问题</th><th>gold SQL</th><th>生成 SQL</th><th style="width:70px">结果</th><th style="width:60px">耗时</th><th style="width:300px">归因</th></tr>
{''.join(rows_html)}
</table>

<h2>四、失败归因</h2>
<div class="note">
<b>① spider_dev_496（形态类，宽口径可通过）</b>——问句「What are the <i>death and injury situations</i>…」，
gold 只取 killed, injured 两列，模型多加了 note 列。剔除 note 后 11 行与 gold 完全一致。
与 Falcon 收敛期结论同源：【结果形态】约束只要求"不加题目未要求列"，但英文 question 的
"situations" 语义边界模糊，模型倾向补充上下文列。<br><br>
<b>② spider_dev_459（口径类，不可两全）</b>——「did the most number of tours」：
gold 直接 <code>JOIN rankings ORDER BY tours DESC LIMIT 1</code>（按单行 tours 最大值所在的行取玩家，
SQLite 弱语义，未聚合也未去重）；模型按 <code>SUM(tours)</code> 逐玩家聚合后取第一，
两者胜者不同（gold: USA/Julia，gen: GRE/Eleni）。该题与 Falcon q218 / BIRD tie-breaking 同属
"gold 依赖未声明语义"类。另：首跑 NVIDIA glm-5.3-flash 对该题思考 300s 超时 504（重试 130s 完成），
与既有记录「NVIDIA 对含糊题易思考到读超时」一致。
</div>

<h2>五、评测口径说明</h2>
<ul>
  <li><b>比对</b>：多重集合比较（行序无关），单元格归一化 NULL→"NULL"、float 保留 4 位小数、字符串去首尾空格；gold 与生成 SQL 均落 MySQL 执行。</li>
  <li><b>宽口径</b>：沿用 Falcon 收敛版比对器的「多余列剔除」层（生成结果列数 = gold+1 时尝试剔除后比对），
      本轮仅 spider_dev_496 受该层影响。</li>
  <li><b>链路</b>：<code>POST /api/conversation</code>（schema_name=spider_&lt;db_id&gt; 绑定库模式，小库直通召回），
      llm_config_id=7，客户端超时 600s；异常题自动重试（q459 首跑 504 已重试）。</li>
  <li><b>行数上限</b>：SQL_MAX_ROWS=2000，本轮 gold 结果集最大 11 行，未触及。</li>
  <li>Token 统计取遥测 llm_calls 回传 usage：Σ入 {sum_p} / Σ出 {sum_c}（出含 reasoning）。</li>
</ul>

<h2>六、结论与下一步</h2>
<ul>
  <li><b>接入结论</b>：Spider 1.0 dev 接入成本低于预期——20 库全为小库，gold SQL 在 MySQL 的可执行率高
      （抽题过程中仅 wta_1 两题因 SQLite 专有语法不兼容被跳过），导入坑集中在类型映射，已沉淀为可复用脚本。</li>
  <li><b>链路结论</b>：小批 10 题未暴露召回/网关/拦截问题；英文元数据 + 英文提问链路顺畅（与 northwind/sakila、Falcon 结论一致）。</li>
  <li><b>下一步（按 B 档方案）</b>：① 按「分层抽样」扩到 dev 抽 100 题（跨 20 库均匀 + 难度分层），
      建立 Spider 正式基线；② 将 Falcon 版比对器（r2 容差 + 列排列 + 多余列剔除）下沉到 <code>spider_bench.py</code> 统一口径；
      ③ 报告新增「gold 口径差」单独分桶，与 Falcon/BIRD 报告口径对齐。</li>
</ul>
</div></body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written:", OUT)


if __name__ == "__main__":
    main()
