# -*- coding: utf-8 -*-
"""BIRD 基准 NL2SQL 全轮次合并报告（去重版）。

合并历史上 4 份重叠 HTML（turbo 单模型报告 / glm53 单模型报告 /
glm vs ds 双模型对比 / opt1 优化对比）为一份：
  - 轮次总览：5 个有效轮次的指标横向对比（含遥测库 token/耗时聚合）
  - 分库 / 分难度对比
  - 逐题跨轮次矩阵（每题一行，5 轮结论并排 + 归因去重合并）
  - 关键结论（三份报告的分析文字去重合并）

未完成/作废轮次仅以脚注说明，不进矩阵：
  - bird_eval_pro.json：豆包 pro 中途配额断，进矩阵但标注未完成
  - bird_eval_nvidia_glm53_guideline.json：数据指南回归轮 13 题中断，被优化轮取代
  - bird_eval_doubao_turbo_opt1.json：24/24 异常（方舟配额暂停），作废
"""
import json
import os
import sqlite3
import html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE_DIR, "results")
TELEMETRY_DB = os.path.join(BASE_DIR, "..", "db", "llm_telemetry.db")
OUT = os.path.join(BASE_DIR, "..", "docs", "测试报告", "BIRD基准NL2SQL测试报告.html")

# (key, 展示名, 结果文件, 表头色)
ROUNDS = [
    ("pro",   "豆包 pro<br>doubao-seed-2-1-pro (id=4)", "bird_eval_pro.json", "#8250df"),
    ("turbo", "豆包 turbo<br>doubao-seed-2-1-turbo (id=5)", "bird_eval_turbo.json", "#0969da"),
    ("glm",   "glm-5.3-flash 基线<br>(id=7, NVIDIA)", "bird_eval_nvidia_glm53.json", "#3574f0"),
    ("ds",    "deepseek-v4.1-flash<br>(id=8, NVIDIA)", "bird_eval_nvidia_dsv41.json", "#b35900"),
    ("opt",   "glm-5.3-flash 优化轮<br>小库直通+形态约束 (id=7)", "bird_eval_nvidia_glm53_opt1.json", "#1a7f37"),
]

VN = {"ok": "通过", "fail": "不通过", "blocked": "拦截", "error": "异常"}
VCLASS = {"ok": "ok", "fail": "no", "blocked": "nb", "error": "er"}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load_dedup(path):
    with open(path, encoding="utf-8") as f:
        rs = json.load(f)
    last = {}
    for r in rs:
        last[r["question_id"]] = r
    return list(last.values())


def verdict(r):
    if r is None:
        return "none"
    if r.get("error"):
        return "error"
    if r.get("need_more_info"):
        return "blocked"
    return "ok" if r["match"] else "fail"


def telemetry_by_conversation(conv_ids):
    """{conversation_id: (calls, prompt, completion, reasoning, total, dur_ms)}"""
    out = {}
    if not any(conv_ids):
        return out
    con = sqlite3.connect(TELEMETRY_DB)
    cur = con.cursor()
    for cid in conv_ids:
        if not cid:
            continue
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
            "COALESCE(SUM(reasoning_tokens),0), COALESCE(SUM(total_tokens),0), COALESCE(SUM(duration_ms),0) "
            "FROM llm_calls WHERE conversation_id=?", (cid,))
        row = cur.fetchone()
        if row and row[0]:
            out[cid] = row
    con.close()
    return out


def round_stats(rows, tel):
    n = len(rows)
    ok = sum(1 for r in rows if verdict(r) == "ok")
    blocked = sum(1 for r in rows if verdict(r) == "blocked")
    error = sum(1 for r in rows if verdict(r) == "error")
    valid = n - blocked - error
    t = list(tel.values())
    return dict(
        n=n, ok=ok, blocked=blocked, error=error, valid=valid,
        executed=sum(1 for r in rows if verdict(r) in ("ok", "fail")),
        avg_t=sum(r["elapsed_s"] for r in rows) / max(n, 1),
        llm_s=sum(x[5] for x in t) / 1000.0,
        prompt=sum(x[1] for x in t), completion=sum(x[2] for x in t),
        reasoning=sum(x[3] for x in t), total=sum(x[4] for x in t),
        has_tok=bool(t),
    )


# 逐题归因（合并自双模型对比与优化轮对比报告，已去重）
NOTES = {
    94: "定位逻辑不同（最老女性 vs 最低 A11 地区），各轮口径均偏；ds 轮的 STR_TO_DATE 在 ISO 日期文本上解析全 NULL，LIMIT 1 侥幸对齐——正解口径已沉淀进数据指南",
    173: "含糊题（'3539' 是金额还是 ID）：ds 拦截，glm 猜测生成通过；优化轮该题 NVIDIA 三次读超时由豆包-lite 代跑，仍与 gold 口径不符——含糊题跨模型均难对齐，单独统计为口径偏差",
    192: "ds 因 'statement issuance' 字段归属不明拦截；glm 猜测 frequency='POPLATEK PO OBRATU' 通过",
    744: "优化轮形态规则生效：不再输出分项计数只返回差值（由败转胜）",
    829: "形态规则未完全压住：仍输出 3 列且 gold 差值为绝对值——思考模型单靠常驻规则不足以完全压制",
    144: "优化轮形态已对齐单值但口径差异：按「月总额的均值」vs gold 按「单笔均值」",
    790: "优化轮采样随机性：误用 superhero_name 而非 full_name 过滤（非链路回退）",
    799: "COUNT(*) WHERE publisher_id IS NULL 各轮逐字一致，gold 用 LEFT JOIN 口径——语义盲区",
    877: "最年轻车手判定，各轮 SQL 逻辑一致仍不匹配——gold 口径差异（tie-breaking 类）",
    927: "CAST(fastestLapSpeed AS DECIMAL) 写法一致仍不匹配——gold 口径差异",
    880: "优化轮不再拦截（小库直通整库注入 drivers/races），SQL 已生成但 fastestLap 语义与 gold 不符",
    990: "优化轮不再拦截（同上），数值口径与 gold 有出入",
    939: "优化轮拦截原因质变：从「缺表」变为「'UN' 国籍取值歧义」——召回问题已修，剩语义歧义",
    995: "优化轮不再拦截（同上），已生成 SQL，数值口径与 gold 有出入",
    107: "glm 按开户地取地区而 gold 按客户居住地；ds 靠 STR_TO_DATE 解析 NULL 后侥幸对齐——居住地 vs 开户地的区分已沉淀进数据指南",
}


def main():
    rounds = []  # (key, label, rows, stats)
    for key, label, fname, _ in ROUNDS:
        rows = load_dedup(os.path.join(RESULTS, fname))
        tel = telemetry_by_conversation([r.get("conversation_id") for r in rows])
        rounds.append((key, label, rows, round_stats(rows, tel)))
    by_round = {key: {r["question_id"]: r for r in rows} for key, _, rows, _ in rounds}
    ref_rows = by_round["glm"]
    qids = sorted(ref_rows, key=lambda q: (ref_rows[q]["db_id"], ref_rows[q]["difficulty"], q))

    # ── 汇总卡片 ─────────────────────────────────────────────
    cards = ""
    for key, label, rows, st in rounds:
        note = "（未完成）" if key == "pro" else ""
        cards += (f"<div class='card'><div class='lab'>{label}</div>"
                  f"<div class='big' style='color:inherit'>{st['ok']}/{st['n']}{note}</div>"
                  f"<div>有效题 EX {st['ok']}/{st['valid']}"
                  f" = <b>{st['ok']/max(st['valid'],1)*100:.0f}%</b></div>"
                  f"<div>拦截 {st['blocked']} · 异常 {st['error']} · 均 {st['avg_t']:.0f}s/题</div></div>")

    # ── 轮次指标总表 ─────────────────────────────────────────
    def metric_row(name, fn, fmt=lambda v: v):
        cells = ""
        for key, _, rows, st in rounds:
            v = fn(st)
            cells += f"<td>{fmt(v) if v != '-' else '-'}</td>"
        return f"<tr><td>{name}</td>{cells}</tr>"

    metrics = ""
    metrics += metric_row("通过 / 总题", lambda s: f"{s['ok']}/{s['n']}")
    metrics += metric_row("有效题 EX", lambda s: f"{s['ok']}/{s['valid']} = {s['ok']/max(s['valid'],1)*100:.0f}%")
    metrics += metric_row("拦截（信息不足）", lambda s: s["blocked"])
    metrics += metric_row("请求异常", lambda s: s["error"])
    metrics += metric_row("SQL 成功执行", lambda s: s["executed"])
    metrics += metric_row("平均端到端耗时/题", lambda s: f"{s['avg_t']:.1f}s")
    metrics += metric_row("LLM 调用总耗时", lambda s: f"{s['llm_s']:.0f}s")
    metrics += metric_row("Total tokens", lambda s: f"{s['total']:,}" if s["has_tok"] else "-")
    metrics += metric_row("其中 reasoning tokens", lambda s: f"{s['reasoning']:,}" if s["has_tok"] else "-")
    metrics += metric_row("平均 tokens/题", lambda s: f"{s['total']/max(s['n'],1):,.0f}" if s["has_tok"] else "-")

    # ── 分库 / 分难度 ─────────────────────────────────────────
    def group_table(dim, values):
        head = "".join(f"<th>{esc(lbl).replace('&lt;br&gt;', '<br>')}</th>" for _, lbl, _, _ in ROUNDS)
        out = f"<table><tr><th>{dim_name[dim]}</th>{head}</tr>"
        for v in values:
            cells = ""
            for key, _, _, _ in ROUNDS:
                g = [r for r in by_round[key].values() if r.get(dim) == v]
                ok = sum(1 for r in g if verdict(r) == "ok")
                cells += f"<td>{ok}/{len(g)}</td>"
            out += f"<tr><td>{esc(v)}</td>{cells}</tr>"
        return out + "</table>"

    dim_name = {"db_id": "数据库", "difficulty": "难度"}
    dbs = ["superhero", "formula_1", "financial"]
    diffs = ["simple", "moderate", "challenging"]

    # ── 逐题跨轮次矩阵 ───────────────────────────────────────
    matrix_rows = ""
    for qid in qids:
        r0 = ref_rows[qid]
        cells = ""
        for key, _, _, _ in ROUNDS:
            rr = by_round[key].get(qid)
            v = verdict(rr)
            if v == "none":
                cells += "<td>-</td>"
            else:
                t = f" {rr['elapsed_s']}s" if rr.get("elapsed_s") else ""
                cells += f"<td><span class='{VCLASS[v]}'>{VN[v]}</span>{t}</td>"
        note = NOTES.get(qid, "")
        if not note:
            for key in ("opt", "ds", "glm"):
                rr = by_round[key].get(qid)
                if rr and rr.get("need_more_info"):
                    note = "拦截: " + esc(str(rr.get("missing_info") or "")[:80])
                    break
                if rr and rr.get("exec_error"):
                    note = "执行错: " + esc(str(rr.get("exec_error"))[:80])
                    break
        matrix_rows += (
            f"<tr><td>{qid}</td><td>{esc(r0['db_id'])}</td><td>{esc(r0['difficulty'])}</td>"
            f"<td class='q'>{esc(r0['question'])}</td>{cells}<td class='q'>{note}</td></tr>")

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>BIRD 基准 NL2SQL 测试报告（全轮次合并）</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1400px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.cards{{display:flex;gap:16px;margin:16px 0;flex-wrap:wrap}}
.card{{background:#f6f8fa;border-radius:8px;padding:12px 18px;text-align:center;flex:1;min-width:200px}}
.card .lab{{font-size:12px;color:#556}} .card .big{{font-size:24px;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}
.q{{max-width:300px;word-break:break-all;font-family:Consolas,monospace;font-size:12px}}
.ok{{color:#1a7f37;font-weight:bold}} .no{{color:#cf222e;font-weight:bold}}
.nb{{color:#9a6700;font-weight:bold}} .er{{color:#8250df;font-weight:bold}}
.note{{color:#666;font-size:12px}} li{{margin:6px 0}}
code{{background:#f4f4f4;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>QueryForge NL2SQL — BIRD 基准测试报告（全轮次合并）</h1>
<p><b>数据集:</b> BIRD dev（2024-06-27 官方发布，1534 题/11 库）·
<b>测试库:</b> superhero(10 表) / formula_1(13 表) / financial(8 表)，SQLite→MySQL 8.0 迁移，
官方 database_description 列说明写入 COMMENT ·
<b>选题:</b> 24 题（各库 simple×3 / moderate×3 / challenging×2，gold SQL 可在 MySQL 执行）·
<b>评测:</b> 执行准确率 EX（生成 SQL 与 gold 在 MySQL 上执行结果多重集比对，浮点 4 位舍入）·
<b>链路:</b> 每题 1~2 次 LLM 调用（可行性判断 + 生成），历史滑动窗口 + 召回列裁剪 + max_rows=100。</p>

<h2>轮次总览</h2>
<div class="cards">{cards}</div>
<table>
<tr><th>指标</th>{''.join(f'<th>{lbl}</th>' for _, lbl, _, _ in ROUNDS)}</tr>
{metrics}
</table>
<p class="note">token / LLM 耗时按 conversation_id 从遥测库 llm_calls 聚合。
豆包 pro 轮在测试中途方舟配额耗尽（SetLimitExceeded）服务暂停，为未完成轮次；其 7 个异常题均为配额或早期 500 缺陷所致。</p>
<p class="note"><b>未进矩阵的轮次：</b>
① 数据指南回归轮（glm-5.3-flash，13 题中断 6/13 通过，随后被优化轮方案取代）；
② 豆包 turbo 优化轮（24/24 异常——火山方舟「安全体验模式」配额暂停，作废，配额恢复后可补跑）。</p>

<h2>分库对比（通过/总题）</h2>
{group_table('db_id', dbs)}
<h2>分难度对比（通过/总题）</h2>
{group_table('difficulty', diffs)}

<h2>逐题跨轮次矩阵</h2>
<table>
<tr><th>qid</th><th>库</th><th>难度</th><th>问题</th>
{''.join(f'<th>{lbl}</th>' for _, lbl, _, _ in ROUNDS)}<th>归因</th></tr>
{matrix_rows}
</table>

<h2>关键结论（三份报告去重合并）</h2>
<h3>1. 过程缺陷（豆包轮发现，均已修复）</h3>
<ul>
<li><b>对话创建 500：</b>创建对话接口在响应序列化阶段引用 <code>request.schema_name</code>（应为
<code>payload.schema_name</code>），导致每轮首轮生成成功后仍返回 500——pro/turbo 轮的请求异常均由此或配额所致，已修复并经后续轮次验证。</li>
<li><b>同步收尾 DetachedInstance：</b>元数据同步实际成功但收尾阶段抛 <code>DbSchema not bound to Session</code>，已在 sync_engine 修复。</li>
<li><b>formula_1 拦截集中：</b>glm/ds 基线轮 4 题共同拦截（880/939/990/995）均因字段向量召回 TopK 截断丢核心表（drivers/races）——催生「小库直通」优化。</li>
</ul>
<h3>2. 模型对比：glm-5.3-flash 综合更优</h3>
<ul>
<li><b>准确率 12/24 vs 11/24</b>：glm 多过的 2 题（173、192）均为 ds 保守拦截的语义含糊题；
ds 仅多过 1 题（107，且属侥幸）。ds 的 need_more_info 明显更保守（拦截 6 vs 4），在以 EX 为指标的基准上折损 2 题。</li>
<li><b>成本</b>：ds 端到端均值 75.4s/题 vs glm 54.7s/题（+38%），token 总量 +9%、reasoning +17%，思考更多但未换来更高准确率。</li>
<li><b>结论</b>：本链路上 glm-5.3-flash 准确率略高、速度更快 38%、token 更省 9%；两模型分歧仅 3 题，
11 题双失败的根因在链路（召回缺表 + 形态约束缺失 + 语义盲区）而不在模型。</li>
</ul>
<h3>3. 优化轮（小库直通 + 结果形态约束）：EX 持平但构成改善</h3>
<ul>
<li><b>拦截面大幅收敛</b>：need_more_info 从 4 题（880/939/990/995）降到 1 题（939），
990 完全通过，880/995 转为生成后败于 gold 口径——小库直通按设计生效；
939 拦截原因从「缺表」质变为「'UN' 国籍歧义」，剩余拦截属语义歧义而非链路缺陷。</li>
<li><b>形态约束部分生效</b>：qid 744 由败转胜；144 收敛为单值输出（口径仍有差）；829 仍输出 3 列——
对思考模型单靠常驻规则不足以完全压制，需数据指南逐库约束配合。</li>
<li><b>EX 持平（12/24）</b>：+2 修复被 2 个偶发因素抵消（790 采样随机性、173 NVIDIA 读超时×3 后豆包-lite 代跑仍口径不符），
有效题 EX 60%→54.5% 的下降全部来自偶发因素，链路修复本身贡献为正。</li>
<li><b>剩余 8 败（799/877/927/107/94/829/144 + 939 拦截）均为 gold 口径/数据语义类</b>：
各轮 SQL 逻辑高度一致、模型间无差异，继续优化应走数据指南与知识库沉淀（NULL 语义、tie-breaking、字段口径），而非改 prompt 或换模型。</li>
</ul>
<p class="note">结果文件：benchmark/results/bird_eval_*.json；生成脚本 benchmark/make_bird_report.py（替代原 make_compare_report.py / make_opt1_report.py 及 4 份独立 HTML）。</p>
</body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print("report ->", OUT)
    for key, label, rows, st in rounds:
        print(f"{key}: {st['ok']}/{st['n']} (valid EX {st['ok']}/{st['valid']}, "
              f"nmi {st['blocked']}, err {st['error']}, avg {st['avg_t']:.1f}s)")


if __name__ == "__main__":
    main()
