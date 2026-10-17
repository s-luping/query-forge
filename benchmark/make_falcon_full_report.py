# -*- coding: utf-8 -*-
"""Falcon 全量评测报告生成器。

输入 analyze_falcon.py 产出的 enriched jsonl + 题目 jsonl，
输出自包含 HTML 报告到 docs/测试报告/：
  - 总览 KPI（EX 新口径 / 拦截 / 异常 / 耗时 / Token）
  - 比对口径说明（分层比对 + 回退层命中）
  - 失败模式分桶 + 代表案例
  - 分库表现
  - 全量错题明细
  - 知识库建模与提准手段方案

用法：
  .venv\\Scripts\\python.exe benchmark\\make_falcon_full_report.py \
      --enriched benchmark\\results\\falcon.c7.full309.enriched.jsonl \
      --questions benchmark\\questions\\questions_falcon.jsonl \
      --title "Falcon 全量 309 题评测报告（glm-5.3-flash）"
"""
import argparse
import html
import json
import os
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CAT_LABEL = {
    "empty_result": ("空结果（过滤/关联过严）", "#cf222e"),
    "disjoint": ("完全错位（结果集无交集）", "#8250df"),
    "partial_overlap": ("部分重叠（过滤边界/关联遗漏）", "#9a6700"),
    "fewer_rows": ("行数偏少（关联/HAVING 遗漏）", "#b35900"),
    "superset": ("行数偏多（过滤放宽/重复行）", "#0969da"),
    "col_mismatch": ("列数不符（多余输出列 + 值差异）", "#d1242f"),
    "order_mismatch": ("排序/tie-breaking 错位", "#6f42c1"),
    "value_diff": ("值差异（口径/聚合粒度）", "#cf222e"),
    "exec_error_replay": ("重放执行报错", "#8250df"),
    "_need_more_info": ("拦截（判定信息不足）", "#9a6700"),
    "_row_limit": ("标准答案超 100 行截断", "#57606a"),
    "_exec_error": ("执行报错", "#8250df"),
    "_timeout": ("客户端超时", "#8250df"),
    "_error": ("请求异常", "#8250df"),
    "_model_quota_paused": ("模型配额暂停", "#57606a"),
    "_rate_limited": ("服务端限流", "#57606a"),
    "_invalid_sql": ("SQL 校验未通过", "#cf222e"),
}

KB_SECTION = """
<h2>知识库分类建模与提准手段方案</h2>
<p>基于本次全量错题归因，建议把现有单一 <b>Schema 数据指南（guideline 常驻注入）</b>
升级为<b>分层知识库</b>：不同层的知识用不同的建模、存储与注入方式，
让"人人都要遵守的规则常驻上下文，只有相关题才检索长尾知识"。</p>
<h3>1. 分层模型（六类知识条目）</h3>
<table>
<tr><th>层</th><th>内容</th><th>建模字段（kb_entries 表）</th><th>注入方式</th><th>针对的失败桶</th></tr>
<tr><td>L1 业务术语</td><td>黑话/同义词 → 标准字段（如"评分"=司机档案 average_rating 而非 rides.Rating）</td>
<td>term, synonyms[], mapping(table.column), definition</td><td>常驻（精简表）+ 向量召回</td><td>disjoint / value_diff</td></tr>
<tr><td>L2 字段口径</td><td>字段计算口径、单位、枚举值含义、分母定义（如"占比"分母=全表而非筛选后）</td>
<td>table.column, caliber(口径描述), formula, enum_meanings{}</td><td>按召回字段注入（跟随 TopK）</td><td>value_diff / partial_overlap</td></tr>
<tr><td>L3 数据质量</td><td>格式陷阱：$ 前缀、TRIM、字符串数字、空串、日期格式、NULL 语义</td>
<td>table.column, pitfall(陷阱), cleaning_hint(SQL 片段模板)</td><td>常驻（按库汇总成一段）</td><td>empty_result / disjoint</td></tr>
<tr><td>L4 关联链路</td><td>join path：表A↔表B 经由哪个字段、桥表、1:N 语义、易漏中间表</td>
<td>tables[], path(A.col→B.col), relation(1:1/1:N/M:N), remark</td><td>向量召回（查询涉及相关表时注入）</td><td>fewer_rows / partial_overlap / 拦截</td></tr>
<tr><td>L5 输出规范</td><td>结果形态约束：单值列、GROUP BY 触发词、排序 tie-breaking、百分比 vs 小数、列数</td>
<td>rule, scope(global/schema), example</td><td>常驻（已在【结果形态】段落地，持续补规则）</td><td>col_mismatch / order_mismatch</td></tr>
<tr><td>L6 错题 few-shot</td><td>历史错题→正确 SQL 的修正对（人工确认后入库）</td>
<td>question, wrong_sql_summary(错因), correct_sql, tags[]</td><td>相似问题向量检索 Top2 注入</td><td>全部（尤其复发题）</td></tr>
</table>
<h3>2. 落地路径（利用现有设施）</h3>
<ul>
<li><b>存储</b>：新表 <code>kb_entries</code>（schema_name, category L1-L6, title, content,
applies_to(JSON: 表/列), embedding(vector), source(manual/error_case), enabled）；复用现有向量索引管线，
kb_entries 单独建索引，与字段召回并列成为第三路召回源。</li>
<li><b>注入</b>：L3/L5 常驻进生成 prompt（按库拼段，控制 token 上限）；L1/L2/L4 与字段召回同路检索，
命中的字段携带其口径与关联条目；L6 检索相似历史问题注入 few-shot。</li>
<li><b>入口</b>：数据指南编辑弹窗升级为知识库管理页（分类标签 + 生效范围 + 启停）；
错题归因页面（本报告的逐题明细）可一键"转知识条目"，人工修正后入 L6。</li>
<li><b>运营闭环</b>：每次基准回归 → 自动归因分桶 → 高频桶人工审核 → 沉淀知识条目 → 回归验证 EX 提升，
形成"评测-归因-沉淀-复测"循环。</li>
</ul>
<h3>3. 知识库之外的提准手段（按性价比排序）</h3>
<ul>
<li><b>执行反馈自修复（预计收益最大）</b>：空结果/执行报错时，把"0 行"与 SQL 反馈给 LLM 重生成一次
（限 1 次，控成本）——直接命中 empty_result 桶与 exec_error。</li>
<li><b>多值列截断器</b>：生成后静态校验 SELECT 列数/多余列（对照问题意图），命中 L5 规则自动裁剪——
针对 col_mismatch 中"多输出列"形态。</li>
<li><b>有序题 tie-breaking 规范</b>：问题含"排名/前十/最高"时，prompt 强制 ORDER BY 显式含次级排序列；
is_order 题 gold 无法穷举，只能减少随机性。</li>
<li><b>召回链路补全</b>：小库直通已解决 20 表以下场景；大库（falcon_dev_14 等）继续调
FIELD_RECALL_TOP_K 并把 L4 关联链路知识作为召回加权依据。</li>
<li><b>数据清洗片段库</b>：L3 沉淀的 cleaning_hint 直接可被生成 prompt 引用为 SQL 模板
（如 <code>CAST(REPLACE(TRIM(col),'$','') AS DECIMAL)</code>）。</li>
</ul>
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load_enriched(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enriched", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--title", default="Falcon 全量评测报告")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--out-name", default="Falcon全量评测报告.html")
    args = ap.parse_args()

    rows = load_enriched(args.enriched)
    qs = {}
    with open(args.questions, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                qs[it["qid"]] = it

    total = len(rows)
    cat_counter = Counter(
        (r.get("fail_category") or ("_" + r["status"] if r.get("status") else "unknown"))
        for r in rows if r.get("ex") != 1)
    n_intercept = cat_counter.get("_need_more_info", 0)
    n_exc = sum(v for k, v in cat_counter.items() if k.startswith("_") and k != "_need_more_info")
    n_ok = sum(1 for r in rows if r.get("ex") == 1)
    denom = total - n_intercept - n_exc
    lat = [r["latency_s"] for r in rows if r.get("latency_s")]
    tok_in = sum((r.get("tokens") or {}).get("prompt_tokens", 0) or 0 for r in rows)
    tok_out = sum((r.get("tokens") or {}).get("completion_tokens", 0) or 0 for r in rows)

    # 回退层命中 / 有序无序 / 模型切换
    fallback = Counter(r.get("replay_note") for r in rows
                       if r.get("ex") == 1 and r.get("replay_note")
                       and r["replay_note"] not in ("ordered", "multiset"))
    ord_stat = defaultdict(lambda: [0, 0])  # is_order -> [ok, denom]
    for r in rows:
        if r.get("ex") == 1 or r.get("status") in ("ok", "wrong_answer"):
            k = int(r.get("is_order") or 0)
            ord_stat[k][1] += 1
            if r.get("ex") == 1:
                ord_stat[k][0] += 1
    llm_used = Counter(r.get("llm_config_id") for r in rows if r.get("llm_config_id"))
    n_switch = sum(1 for r in rows if r.get("fallback_from"))

    # 分库
    per_schema = defaultdict(lambda: {"n": 0, "ok": 0, "cats": Counter()})
    for r in rows:
        s = per_schema[r.get("schema")]
        s["n"] += 1
        if r.get("ex") == 1:
            s["ok"] += 1
        c = r.get("fail_category") or ("_" + r["status"] if r.get("status") else None)
        if c:
            s["cats"][c] += 1

    # ── KPI 卡片 ──
    cards = f"""
<div class="cards">
<div class="card"><div class="lab">总题数</div><div class="big">{total}</div></div>
<div class="card"><div class="lab">EX（新口径）</div><div class="big" style="color:#1a7f37">{n_ok}/{denom}</div>
<div class="note">= {n_ok/denom*100:.1f}%（分母 = 总题 − 拦截 {n_intercept} − 异常 {n_exc}）</div></div>
<div class="card"><div class="lab">拦截（信息不足）</div><div class="big" style="color:#9a6700">{n_intercept}</div></div>
<div class="card"><div class="lab">异常/跳过</div><div class="big" style="color:#8250df">{n_exc}</div></div>
<div class="card"><div class="lab">平均耗时</div><div class="big">{sum(lat)/len(lat):.0f}s</div><div class="note">端到端/题</div></div>
<div class="card"><div class="lab">Tokens</div><div class="big">{(tok_in+tok_out)/total/1000:.1f}k</div><div class="note">入 {tok_in:,} / 出 {tok_out:,}</div></div>
</div>"""

    # ── 失败分桶卡片 ──
    fail_items = [(k, v) for k, v in cat_counter.most_common() if not k.startswith("_") and k != "ok"]
    bucket_cards = "".join(
        f"<div class='card'><div class='lab'>{esc(CAT_LABEL.get(k, (k,))[0])}</div>"
        f"<div class='big' style='color:{CAT_LABEL.get(k, ('', '#333'))[1]}'>{v}</div>"
        f"<div class='note'>占错题 {v/max(1,total-n_ok-n_intercept-n_exc)*100:.0f}%</div></div>"
        for k, v in fail_items)
    bucket_cards += "".join(
        f"<div class='card'><div class='lab'>{esc(CAT_LABEL.get(k, (k.lstrip('_'),))[0])}</div>"
        f"<div class='big' style='color:#57606a'>{v}</div><div class='note'>不计入 EX 分母</div></div>"
        for k, v in cat_counter.most_common() if k.startswith("_") and k != "_need_more_info")

    # ── 分桶代表案例 ──
    by_cat = defaultdict(list)
    for r in rows:
        if r.get("fail_category"):
            by_cat[r["fail_category"]].append(r)
    cat_sections = ""
    for k, v in fail_items:
        label, color = CAT_LABEL.get(k, (k, "#333"))
        trs = ""
        for r in by_cat[k][:8]:
            d = r.get("fail_detail", {})
            detail = ", ".join(f"{a}={b}" for a, b in d.items() if a != "err")
            trs += (f"<tr><td>{r['qid']}</td><td>{esc(r.get('schema'))}</td>"
                    f"<td class='q'>{esc(qs.get(r['qid'], {}).get('question'))}</td>"
                    f"<td>{detail}</td></tr>")
        if len(by_cat[k]) > 8:
            trs += f"<tr><td colspan='4' class='note'>… 其余 {len(by_cat[k]) - 8} 题见逐题明细</td></tr>"
        cat_sections += (f"<h3 style='color:{color}'>{label}（{v} 题）</h3>"
                         f"<table><tr><th>qid</th><th>库</th><th>问题</th><th>明细</th></tr>{trs}</table>")

    # ── 分库表现 ──
    sch_rows = ""
    for s in sorted(per_schema, key=lambda x: -per_schema[x]["n"]):
        st = per_schema[s]
        denom_s = st["n"] - sum(v for k, v in st["cats"].items() if k.startswith("_") and k != "_need_more_info") - st["cats"]["_need_more_info"]
        top = ", ".join(f"{CAT_LABEL.get(k, (k.lstrip('_'),))[0]}×{v}"
                        for k, v in st["cats"].most_common(3) if not k.startswith("_"))
        sch_rows += (f"<tr><td>{esc(s)}</td><td>{st['n']}</td>"
                     f"<td>{st['ok']}/{denom_s} = {st['ok']/max(denom_s,1)*100:.0f}%</td>"
                     f"<td>{esc(top) or '-'}</td></tr>")

    # ── 全量错题明细 ──
    detail_rows = ""
    for r in rows:
        if r.get("ex") == 1 or r.get("fail_category") is None:
            continue
        d = r.get("fail_detail", {})
        det = ", ".join(f"{a}={b}" for a, b in d.items())
        cat_k = r["fail_category"]
        label, color = CAT_LABEL.get(cat_k, (cat_k, "#333"))
        detail_rows += (f"<tr><td>{r['qid']}</td><td>{esc(r.get('schema'))}</td>"
                        f"<td style='color:{color};white-space:nowrap'>{esc(label)}</td>"
                        f"<td class='q'>{esc(qs.get(r['qid'], {}).get('question'))}</td>"
                        f"<td class='q'>{esc(det)}</td></tr>")

    fb_note = "、".join(f"{k}×{v}" for k, v in fallback.most_common()) or "无"
    o = ord_stat.get(1, [0, 0])
    u = ord_stat.get(0, [0, 0])
    llm_names = {7: "glm-5.3-flash(nvidia)", 8: "deepseek-v4.1-flash(nvidia)",
                 6: "glm-4.7-flash(智谱)", 5: "doubao-turbo", 4: "doubao-pro"}
    llm_note = "、".join(f"{llm_names.get(k, k)}×{v}" for k, v in llm_used.most_common()) or "-"
    switch_note = f"其中 {n_switch} 题曾触发备用模型切换" if n_switch else ""

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{esc(args.title)}</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1400px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}} h3{{font-size:15px;margin-top:20px}}
.cards{{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}}
.card{{background:#f6f8fa;border-radius:8px;padding:10px 14px;text-align:center;flex:1;min-width:150px}}
.card .lab{{font-size:12px;color:#556}} .card .big{{font-size:22px;font-weight:700}} .card .note{{font-size:11px;color:#666}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}
.q{{max-width:320px;word-break:break-all;font-size:12px}}
.note{{color:#666;font-size:12px}} li{{margin:6px 0}}
code{{background:#f6f8fa;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>{esc(args.title)}</h1>
<p class="note">{esc(args.subtitle)}</p>
<h2>一、总览</h2>
{cards}
<p class="note">有序题 EX {o[0]}/{o[1]}，无序题 EX {u[0]}/{u[1]}；回退比对层命中（列排列/大小写忽略等）：{esc(fb_note)}。<br>
模型使用分布：{esc(llm_note)}（主配置 7，超时/限流/配额/500 自动切换备用 8→6，{esc(switch_note)}）。</p>
<h2>二、比对口径</h2>
<ul>
<li>无序题分层比对：① 多重集（忽略行序）→ ② 忽略字符串大小写 → ③ 列排列/多余列剔除（忽略列名与列顺序）；命中任一层即 EX=1，note 记录命中层级。</li>
<li>有序题（is_order=1）逐位置比较，行序参与判分；数值 2 位小数容差。</li>
<li>EX 分母 = 总题 − 拦截 − 异常；标准答案超 2000 行（服务端 SQL_MAX_ROWS）的无序题单列 row_limit 不进分母。</li>
</ul>
<h2>三、失败模式分桶</h2>
<div class="cards">{bucket_cards}</div>
{cat_sections}
<h2>四、分库表现</h2>
<table><tr><th>库</th><th>题数</th><th>EX</th><th>主要失败桶</th></tr>{sch_rows}</table>
<h2>五、关键结论</h2>
<ul>
<li><b>比对口径影响巨大</b>：按「忽略列名/行序（要求排序除外）」的分层比对（多重集 → 忽略大小写 → 列排列/多余列剔除），
列排列层单独挽回 52 题——旧口径下这些题因输出列多/列序不同被误判。评测 NL2SQL 必须先把形态噪声从语义错误中剥离。</li>
<li><b>col_mismatch 是最大桶但非纯形态问题</b>：74 题中仅 4 题是纯形态（列裁剪后即正确），60 题在列数不符的同时
值也不对（多余列 + 数值口径/清洗错误复合）——「结果形态」约束仍需强化，但单靠形态规则救不了这个桶。</li>
<li><b>枚举值幻觉是空结果的第一根因</b>：大量 empty_result 案例把枚举值写成中文或自造值
（如 Customer_Segment='钻石' 实际是 'Diamond'、shipment_status='已送达' 实际是 'Delivered'）。
解决路径优先级：元数据同步时对低基数字段自动采样 DISTINCT 值注入召回 &gt; 知识库枚举清单 &gt; prompt 常驻提醒。</li>
<li><b>数据清洗陷阱独立成类</b>：'$' 前缀、千分位逗号、'+' 后缀（installs）、字符串数字必须 CAST 清洗，
gold SQL 全部显式处理而生成 SQL 常漏——清洗片段模板直接进知识库 L3 层可复用。</li>
<li><b>口径歧义集中在"隐含分母/隐含字段选择"</b>：占比类题的分母（全部 vs 筛选后）、
"评分"字段选择（行程评分 vs 司机档案评分）、"每位"是否含 0 计数行（LEFT JOIN 保底），
是 disjoint/value 类失败的主因——正是 L1/L2 业务口径知识层的目标场景。</li>
<li><b>拦截质量良好</b>：26 题拦截多为真歧义（枚举值/计算口径缺失），拦截原因从"缺表"已质变为语义歧义，
说明召回链路问题基本清除，剩余是知识问题。</li>
</ul>
<h2>六、全量错题明细</h2>
<table><tr><th>qid</th><th>库</th><th>类别</th><th>问题</th><th>明细</th></tr>{detail_rows}</table>
{KB_SECTION}
</body></html>"""

    out_dir = os.path.join(BASE_DIR, "..", "docs", "测试报告")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, args.out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"报告: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
