# -*- coding: utf-8 -*-
"""BIRD 基准双模型对比报告（NVIDIA glm-5.3-flash vs deepseek-v4.1-flash）。

glm53 轮未记录 llm_info，token/LLM 耗时按 conversation_id 从遥测库 llm_calls 聚合；
deepseek 轮直接读结果文件里的 llm_info。
"""
import json
import sqlite3
import html

RESULTS = r"D:\projects\query-forge\benchmark\results"
TELEMETRY_DB = r"D:\projects\query-forge\db\llm_telemetry.db"
GLM = RESULTS + r"\bird_eval_nvidia_glm53.json"
DS = RESULTS + r"\bird_eval_nvidia_dsv41.json"
OUT = r"d:\projects\query-forge\docs\BIRD基准NL2SQL双模型对比报告_nvidia.html"

GLM_LABEL = "nvidia glm-5.3-flash (id=7)"
DS_LABEL = "nvidia deepseek-v4.1-flash (id=8)"
FINDINGS = ""  # 差异归因文字，数据确认后填入


def load_dedup(path):
    with open(path, encoding="utf-8") as f:
        rs = json.load(f)
    last = {}
    for r in rs:
        last[r["question_id"]] = r
    return list(last.values())


def telemetry_by_conversation(conv_ids):
    """{conversation_id: (calls, prompt, completion, reasoning, total, dur_ms)}"""
    out = {}
    con = sqlite3.connect(TELEMETRY_DB)
    cur = con.cursor()
    for cid in conv_ids:
        if not cid:
            continue
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
            "COALESCE(SUM(reasoning_tokens),0), COALESCE(SUM(total_tokens),0), COALESCE(SUM(duration_ms),0) "
            "FROM llm_calls WHERE conversation_id=?", (cid,))
        out[cid] = cur.fetchone()
    con.close()
    return out


def verdict(r):
    if r.get("error"):
        return "error"
    if r.get("need_more_info"):
        return "blocked"
    return "ok" if r["match"] else "fail"


VN = {"ok": "通过", "fail": "不通过", "blocked": "拦截", "error": "异常"}
VCLASS = {"ok": "ok", "fail": "no", "blocked": "nb", "error": "er"}


def model_stats(rs, tokens_of):
    n = len(rs)
    executed = sum(1 for r in rs if verdict(r) in ("ok", "fail"))
    toks = [tokens_of(r) for r in rs if tokens_of(r)]
    return dict(
        n=n,
        ok=sum(1 for r in rs if verdict(r) == "ok"),
        blocked=sum(1 for r in rs if verdict(r) == "blocked"),
        error=sum(1 for r in rs if verdict(r) == "error"),
        executed=executed,
        avg_t=sum(r["elapsed_s"] for r in rs) / max(n, 1),
        prompt=sum(t[0] for t in toks), completion=sum(t[1] for t in toks),
        reasoning=sum(t[2] for t in toks), total=sum(t[3] for t in toks),
        llm_s=sum(t[4] for t in toks) / 1000.0,
        has_tok=bool(toks),
    )


def main():
    glm = load_dedup(GLM)
    ds = load_dedup(DS)
    ds_by_qid = {r["question_id"]: r for r in ds}

    # glm53 token/耗时：遥测库按 conversation_id 聚合
    tmap = telemetry_by_conversation([r.get("conversation_id") for r in glm])

    def glm_tok(r):
        row = tmap.get(r.get("conversation_id"))
        if not row or not row[0]:
            return None
        return row[1], row[2], row[3], row[4], row[5]

    def ds_tok(r):
        li = r.get("llm_info")
        if not li:
            return None
        return (li.get("prompt_tokens", 0), li.get("completion_tokens", 0),
                li.get("reasoning_tokens", 0), li.get("total_tokens", 0),
                li.get("duration_ms", 0))

    sg = model_stats(glm, glm_tok)
    sd = model_stats(ds, ds_tok)

    def pct(a, b):
        return f"{a}/{b} ({a/max(b,1)*100:.0f}%)"

    # ── 分库 / 分难度 ──────────────────────────────────────────
    dbs = ["superhero", "formula_1", "financial"]
    diffs = ["simple", "moderate", "challenging"]

    def group_rows(dim, values):
        rows = []
        for v in values:
            g = [r for r in glm if r[dim] == v]
            d = [r for r in ds if r[dim] == v]
            gok = sum(1 for r in g if verdict(r) == "ok")
            dok = sum(1 for r in d if verdict(r) == "ok")
            gt = sum(r["elapsed_s"] for r in g) / max(len(g), 1)
            dt = sum(r["elapsed_s"] for r in d) / max(len(d), 1)
            rows.append(f"<tr><td>{esc(v)}</td><td>{gok}/{len(g)}</td>"
                        f"<td>{dok}/{len(d)}</td><td>{gt:.0f}s</td><td>{dt:.0f}s</td></tr>")
        return "".join(rows)

    # ── 逐题矩阵 ──────────────────────────────────────────────
    CAT = {"ok_ok": "双通过", "ok_fail": "仅glm过", "fail_ok": "仅ds过",
           "ok_blocked": "仅glm过", "blocked_ok": "仅ds过",
           "blocked_blocked": "双拦截", "fail_fail": "双不通过"}
    matrix_rows = []
    div = {"ok_ok": 0, "glm_only": 0, "ds_only": 0, "both_fail": 0}
    for r in sorted(glm, key=lambda x: (x["db_id"], x["difficulty"], x["question_id"])):
        d = ds_by_qid.get(r["question_id"], {})
        vg, vd = verdict(r), verdict(d)
        key = (vg, vd)
        if vg == "ok" and vd == "ok":
            cat, color = "双通过", "#1a7f37"
            div["ok_ok"] += 1
        elif vg == "ok":
            cat, color = f"仅glm过（ds {VN[vd]}）", "#9a6700"
            div["glm_only"] += 1
        elif vd == "ok":
            cat, color = f"仅ds过（glm {VN[vg]}）", "#0969da"
            div["ds_only"] += 1
        else:
            cat, color = f"双失败（glm {VN[vg]} / ds {VN[vd]}）", "#cf222e"
            div["both_fail"] += 1
        def cell(rr):
            if rr is None:
                return "-"
            v = verdict(rr)
            return f'<span class="{VCLASS[v]}">{VN[v]}</span> {rr["elapsed_s"]}s'
        note = ""
        for rr in (r, d):
            if rr.get("need_more_info"):
                note = "拦截: " + esc(str(rr.get("missing_info") or "")[:80])
                break
            if rr.get("exec_error"):
                note = "执行错: " + esc(str(rr.get("exec_error"))[:80])
                break
        matrix_rows.append(
            f'<tr><td>{r["question_id"]}</td><td>{esc(r["db_id"])}</td>'
            f'<td>{esc(r["difficulty"])}</td><td class="q">{esc(r["question"])}</td>'
            f'<td>{cell(r)}</td><td>{cell(d)}</td>'
            f'<td style="color:{color};font-weight:bold">{cat}</td>'
            f'<td class="q">{note}</td></tr>')

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>BIRD 基准双模型对比报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1240px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.sum{{display:flex;gap:16px;margin:16px 0;flex-wrap:wrap}}
.card{{background:#f6f8fa;border-radius:8px;padding:14px 20px;text-align:center;flex:1;min-width:200px}}
.card b{{font-size:24px;display:block}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
td,th{{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}
.q{{max-width:320px;word-break:break-all;font-family:Consolas,monospace;font-size:12px}}
.ok{{color:#1a7f37;font-weight:bold}} .no{{color:#cf222e;font-weight:bold}}
.nb{{color:#9a6700;font-weight:bold}} .er{{color:#8250df;font-weight:bold}}
</style></head><body>
<h1>QueryForge NL2SQL — BIRD 基准双模型对比报告（NVIDIA NIM）</h1>
<p><b>数据集:</b> BIRD dev 选题 24 题（superhero / formula_1 / financial 各 simple×3 / moderate×3 / challenging×2）·
<b>评测:</b> 执行准确率（生成 SQL 与 gold SQL 在 MySQL 上执行结果多重集比对，浮点 4 位舍入）·
<b>链路:</b> 每题 1~2 次 LLM 调用（可行性判断 + 生成），历史滑动窗口 + 召回列裁剪 + max_rows=100。</p>

<div class="sum">
 <div class="card"><b>{pct(sg['ok'], sg['n'])}</b>{esc(GLM_LABEL)} 执行准确率</div>
 <div class="card"><b>{pct(sd['ok'], sd['n'])}</b>{esc(DS_LABEL)} 执行准确率</div>
</div>

<h2>总体指标对比</h2>
<table>
<tr><th>维度</th><th>{esc(GLM_LABEL)}</th><th>{esc(DS_LABEL)}</th></tr>
<tr><td>通过 / 总题</td><td>{sg['ok']}/{sg['n']}</td><td>{sd['ok']}/{sd['n']}</td></tr>
<tr><td>拦截（信息不足）</td><td>{sg['blocked']}</td><td>{sd['blocked']}</td></tr>
<tr><td>请求异常</td><td>{sg['error']}</td><td>{sd['error']}</td></tr>
<tr><td>SQL 成功执行</td><td>{sg['executed']}</td><td>{sd['executed']}</td></tr>
<tr><td>平均端到端耗时/题</td><td>{sg['avg_t']:.1f}s</td><td>{sd['avg_t']:.1f}s</td></tr>
<tr><td>LLM 调用总耗时</td><td>{sg['llm_s']:.0f}s</td><td>{sd['llm_s']:.0f}s</td></tr>
<tr><td>Prompt tokens</td><td>{sg['prompt']:,}</td><td>{sd['prompt']:,}</td></tr>
<tr><td>Completion tokens</td><td>{sg['completion']:,}</td><td>{sd['completion']:,}</td></tr>
<tr><td>其中 reasoning tokens</td><td>{sg['reasoning']:,}</td><td>{sd['reasoning']:,}</td></tr>
<tr><td>Total tokens</td><td>{sg['total']:,}</td><td>{sd['total']:,}</td></tr>
<tr><td>平均 tokens/题</td><td>{sg['total']/max(sg['n'],1):,.0f}</td><td>{sd['total']/max(sd['n'],1):,.0f}</td></tr>
</table>
<p style="color:#666;font-size:12px">注：glm 轮 token/LLM 耗时按 conversation_id 从遥测库聚合；ds 轮来自响应 llm_info。</p>

<h2>分库对比</h2>
<table><tr><th>数据库</th><th>glm 通过</th><th>ds 通过</th><th>glm 均耗时</th><th>ds 均耗时</th></tr>
{group_rows('db_id', dbs)}</table>

<h2>分难度对比</h2>
<table><tr><th>难度</th><th>glm 通过</th><th>ds 通过</th><th>glm 均耗时</th><th>ds 均耗时</th></tr>
{group_rows('difficulty', diffs)}</table>

<h2>分歧分布</h2>
<table>
<tr><th>双通过</th><th>仅 glm 过</th><th>仅 ds 过</th><th>双失败</th></tr>
<tr><td>{div['ok_ok']}</td><td>{div['glm_only']}</td><td>{div['ds_only']}</td><td>{div['both_fail']}</td></tr>
</table>

<h2>逐题对比矩阵</h2>
<table>
<tr><th>qid</th><th>库</th><th>难度</th><th>问题</th><th>glm</th><th>ds</th><th>分歧归类</th><th>说明</th></tr>
{''.join(matrix_rows)}
</table>

<h2>差异归因分析</h2>
{FINDINGS}
</body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print("report ->", OUT)
    print("glm:", sg)
    print("ds:", sd)
    print("div:", div)


def esc(s):
    return html.escape(str(s if s is not None else ""))


if __name__ == "__main__":
    main()
