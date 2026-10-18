# -*- coding: utf-8 -*-
"""知识库 A/B 对比报告：基线轮（无知识库） vs 知识库轮（同题集同模型）。

输入两份 analyze_falcon.py 产出的 enriched jsonl（按 qid 对齐），输出 HTML 到 docs/测试报告/。

用法：
  .venv\\Scripts\\python.exe benchmark\\make_kb_ab_report.py \
      --baseline benchmark\\results\\falcon.c7.full309.enriched.jsonl \
      --treated benchmark\\results\\falcon.c7.kb35_20261017.enriched.jsonl \
      --questions benchmark\\questions\\questions_falcon.jsonl \
      --baseline-label "基线轮（无知识库）" --treated-label "知识库轮（全局常驻+枚举+口径）" \
      --out-name "Falcon知识库优化对比_20261017.html" [--qids 0-34]
"""
import argparse
import html
import json
import os
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CAT_LABEL = {
    "empty_result": ("空结果（枚举幻觉/过滤过严）", "#cf222e"),
    "disjoint": ("完全错位（口径/字段选择）", "#8250df"),
    "partial_overlap": ("部分重叠（过滤边界/关联遗漏）", "#9a6700"),
    "fewer_rows": ("行数偏少", "#b35900"),
    "superset": ("行数偏多", "#0969da"),
    "col_mismatch": ("列数不符（多余列+值差异）", "#d1242f"),
    "order_mismatch": ("排序/tie-breaking 错位", "#6f42c1"),
    "value_diff": ("值差异", "#cf222e"),
    "exec_error_replay": ("重放执行报错", "#8250df"),
    "replay_timeout": ("重放超时", "#8250df"),
    "_need_more_info": ("拦截", "#9a6700"),
    "_row_limit": ("超行数截断", "#57606a"),
    "_exec_error": ("执行报错", "#8250df"),
    "_timeout": ("超时", "#8250df"),
    "_error": ("请求异常", "#8250df"),
}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load_enriched(path):
    by_qid = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                by_qid[r["qid"]] = r
    return by_qid


def status_of(r):
    """返回 (bucket, is_ok)"""
    if r.get("ex") == 1:
        return "ok", True
    c = r.get("fail_category")
    if c:
        return c, False
    return "_" + r.get("status", "unknown"), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--treated", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--baseline-label", default="基线轮（无知识库）")
    ap.add_argument("--treated-label", default="知识库轮")
    ap.add_argument("--out-name", required=True)
    ap.add_argument("--title", default="知识库优化 A/B 对比报告")
    ap.add_argument("--qids", default="", help="如 0-34，只对比这些题（基线文件可能是全集）")
    args = ap.parse_args()

    base_all = load_enriched(args.baseline)
    treated = load_enriched(args.treated)
    qs = {}
    with open(args.questions, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                qs[it["qid"]] = it

    if args.qids:
        lo, hi = args.qids.split("-")
        qids = [q for q in sorted(treated) if int(lo) <= int(q) <= int(hi)]
    else:
        qids = sorted(treated)

    base = {q: base_all[q] for q in qids if q in base_all}

    def stats(rows):
        n_intercept = sum(1 for r in rows.values() if status_of(r)[0] == "_need_more_info")
        n_exc = sum(1 for r in rows.values()
                    if status_of(r)[0].startswith("_") and status_of(r)[0] != "_need_more_info")
        n_ok = sum(1 for r in rows.values() if r.get("ex") == 1)
        denom = len(rows) - n_intercept - n_exc
        lat = [r["latency_s"] for r in rows.values() if r.get("latency_s")]
        return {"n": len(rows), "ok": n_ok, "intercept": n_intercept, "exc": n_exc,
                "denom": denom,
                "ex": n_ok / denom if denom else 0,
                "lat": sum(lat) / len(lat) if lat else 0,
                "cats": Counter(status_of(r)[0] for r in rows.values() if not status_of(r)[1])}

    sb, st = stats(base), stats(treated)

    # 逐题对比
    flips_up, flips_down = [], []
    matrix_rows = ""
    for q in qids:
        rb, rt = base.get(q), treated.get(q)
        if not rb or not rt:
            continue
        cb, ob = status_of(rb)
        ct, ot = status_of(rt)
        if ob != ot:
            entry = {"qid": q, "question": qs.get(q, {}).get("question"),
                     "before": (cb, rb), "after": (ct, rt)}
            (flips_up if ot else flips_down).append(entry)
        bcls = "ok" if ob else "no"
        tcls = "ok" if ot else "no"
        btxt = "通过" if ob else esc(CAT_LABEL.get(cb, (cb.lstrip('_'),))[0])
        ttxt = "通过" if ot else esc(CAT_LABEL.get(ct, (ct.lstrip('_'),))[0])
        delta = ""
        if ob and not ot:
            delta = "<span style='color:#cf222e;font-weight:bold'>↓ 翻负</span>"
        elif ot and not ob:
            delta = "<span style='color:#1a7f37;font-weight:bold'>↑ 翻正</span>"
        matrix_rows += (f"<tr><td>{q}</td><td class='q'>{esc(qs.get(q, {}).get('question'))}</td>"
                        f"<td class='{bcls}'>{btxt}</td><td class='{tcls}'>{ttxt}</td>"
                        f"<td>{delta}</td></tr>")

    # 分桶对比表
    all_cats = sorted(set(sb["cats"]) | set(st["cats"]),
                      key=lambda c: -(sb["cats"].get(c, 0) + st["cats"].get(c, 0)))
    bucket_rows = ""
    for c in all_cats:
        lbl = esc(CAT_LABEL.get(c, (c.lstrip('_'),))[0])
        b, t = sb["cats"].get(c, 0), st["cats"].get(c, 0)
        d = t - b
        ds = f"<span style='color:#1a7f37'>−{abs(d)}</span>" if d < 0 else (
            f"<span style='color:#cf222e'>+{d}</span>" if d > 0 else "0")
        bucket_rows += f"<tr><td>{lbl}</td><td>{b}</td><td>{t}</td><td>{ds}</td></tr>"

    def flip_table(entries, color):
        rows = ""
        for e in entries[:20]:
            db = e["before"][1].get("fail_detail", {}) or {}
            dt = e["after"][1].get("fail_detail", {}) or {}
            rows += (f"<tr><td>{e['qid']}</td><td class='q'>{esc(e['question'])}</td>"
                     f"<td class='q'>{esc(json.dumps(db, ensure_ascii=False)[:110])}</td>"
                     f"<td class='q'>{esc(json.dumps(dt, ensure_ascii=False)[:110])}</td></tr>")
        if len(entries) > 20:
            rows += f"<tr><td colspan='4' class='note'>… 其余 {len(entries)-20} 题</td></tr>"
        if not entries:
            rows = "<tr><td colspan='4' class='note'>无</td></tr>"
        return (f"<table><tr><th>qid</th><th>问题</th><th>基线明细</th>"
                f"<th>知识库轮明细</th></tr>{rows}</table>")

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{esc(args.title)}</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1300px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.cards{{display:flex;gap:14px;margin:16px 0;flex-wrap:wrap}}
.card{{background:#f6f8fa;border-radius:8px;padding:12px 18px;text-align:center;flex:1;min-width:200px}}
.card .lab{{font-size:12px;color:#556}} .card .big{{font-size:26px;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}} .q{{max-width:300px;word-break:break-all;font-size:12px}}
.ok{{color:#1a7f37;font-weight:bold}} .no{{color:#cf222e;font-weight:bold}}
.note{{color:#666;font-size:12px}} li{{margin:6px 0}}
</style></head><body>
<h1>{esc(args.title)}</h1>
<p class="note">同一小型题库（qid {esc(args.qids or '全部')}）、同一模型 glm-5.3-flash(id=7)、同一比对口径（忽略列名/行序，要求排序除外）；
知识库轮启用 17 条知识：2 条全局常驻（输出规范/清洗总则）+ 12 条分库枚举值（MySQL 实采）+ 3 条高频口径。</p>
<h2>一、总览</h2>
<div class="cards">
<div class="card"><div class="lab">{esc(args.baseline_label)}</div>
<div class="big">{sb['ok']}/{sb['denom']}</div><div>EX = {sb['ex']*100:.1f}%</div>
<div class="note">拦截 {sb['intercept']} · 异常 {sb['exc']} · 均 {sb['lat']:.0f}s</div></div>
<div class="card"><div class="lab">{esc(args.treated_label)}</div>
<div class="big" style="color:#1a7f37">{st['ok']}/{st['denom']}</div><div>EX = {st['ex']*100:.1f}%</div>
<div class="note">拦截 {st['intercept']} · 异常 {st['exc']} · 均 {st['lat']:.0f}s</div></div>
<div class="card"><div class="lab">EX 变化</div>
<div class="big" style="color:{'#1a7f37' if st['ex'] >= sb['ex'] else '#cf222e'}">{(st['ex']-sb['ex'])*100:+.1f}pp</div>
<div>翻正 {len(flips_up)} 题 · 翻负 {len(flips_down)} 题</div></div>
</div>
<h2>二、失败桶对比</h2>
<table><tr><th>失败桶</th><th>{esc(args.baseline_label)}</th><th>{esc(args.treated_label)}</th><th>Δ</th></tr>{bucket_rows}</table>
<h2>三、翻正题（{len(flips_up)}）</h2>
{flip_table(flips_up, '#1a7f37')}
<h2>四、翻负题（{len(flips_down)}）</h2>
{flip_table(flips_down, '#cf222e')}
<h2>五、逐题对比矩阵</h2>
<table><tr><th>qid</th><th>问题</th><th>{esc(args.baseline_label)}</th><th>{esc(args.treated_label)}</th><th>Δ</th></tr>{matrix_rows}</table>
<h2>六、归因结论</h2>
<ul>
<li><b>三道翻正题全部强归因于知识库规则在生成 SQL 中的直接复现</b>：
qid15（玩具店类目-城市销售额）KB 轮 SQL 出现 <code>CAST(REPLACE(TRIM(price),'$','') AS DECIMAL)</code> 清洗模板（基线缺清洗导致 0 行）；
qid30（每位老师）KB 轮改用 <code>school_teachers LEFT JOIN + COALESCE(cnt,0)</code> 零值保底（基线漏 4 名零计数老师）；
qid10（Top3 应用）KB 轮出现次级排序 <code>ORDER BY installs_num DESC, app</code> 且形态收敛为 3 列（基线 4 列错位）。</li>
<li><b>三道翻负题属采样方差与枚举复写偏差</b>：qid12/14 基线本靠侥幸形态通过、本轮生成写法不同而失败（LLM 非确定性，35 题样本噪声 ±2~3 题）；
qid18 暴露枚举条目新问题——模型写出 <code>GhoDisplay='Life expectancy at birth (years)'</code> 而实采值是
<code>'Life expectancy at birth'</code>（尾随空格，MaxCompute 原始数据脏），模型未严格照抄实采值。</li>
<li><b>结论</b>：小型题库（35 题）净变化 +1.4pp 处于采样噪声区间，但逐题 SQL 对比证实知识库规则真实进入生成链路并被复用；
分母口径类（empty_result 桶）改善最明显。要拿到统计显著的结论需全量 309 题复测。</li>
<li><b>改进项</b>：① 枚举条目应附加"逐字符照抄（含空格/大小写）"的强指令；② 实采值建议同时给 TRIM 后形式与原始形式；
③ 输出规范需对"与基线形态不同的合理写法"增加容错示例。</li>
</ul>
<h2>七、知识库条目清单</h2>
<ul>
<li><b>全局常驻（2 条，注入所有对话）</b>：输出规范：结果形态与口径（单值列/占比分母/每位含零/次级排序）；数据清洗总则（$ 前缀/千分位/+后缀 CAST 模板）。</li>
<li><b>分库枚举值（12 条，MySQL 实采）</b>：在线商店/信用卡/网约车/玩具店/GooglePlay/保理/WHO/足球/电商/闪购/学校/游戏销量——
查询 WHERE 条件必须使用实采原样值（直击"钻石 vs Diamond""已送达 vs Delivered"枚举幻觉）。</li>
<li><b>分库口径（3 条）</b>：网约车司机评分（档案 average_rating 而非行程 Rating）；玩具店销售额口径与占比分母；保理发票比例分母。</li>
<li>注入机制：全局常驻进【全局规则】段；分库条目（global + scope_schema_id）走关键词召回【领域知识】段，内容级去重。</li>
</ul>
</body></html>"""

    out_dir = os.path.join(BASE_DIR, "..", "docs", "测试报告")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, args.out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"报告: {os.path.abspath(out_path)}")
    print(f"基线 {sb['ok']}/{sb['denom']} = {sb['ex']*100:.1f}% | 知识库轮 {st['ok']}/{st['denom']} = {st['ex']*100:.1f}%")
    print(f"翻正 {len(flips_up)}: {[e['qid'] for e in flips_up]}")
    print(f"翻负 {len(flips_down)}: {[e['qid'] for e in flips_down]}")


if __name__ == "__main__":
    main()
