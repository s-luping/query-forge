# -*- coding: utf-8 -*-
"""NL2SQL 基准批量评测脚本（对应 docs/NL2SQL基准测试方案.md 第 3/5 节）。

流程：登录 QueryForge → 遍历题目调 POST /api/conversation →
执行生成的 SQL → 与 Falcon dev.json 自带标准答案比对（EX）→
逐题 JSONL 断点续跑 → 汇总指标。

比对采用 DB-GPT Benchmark 同款方式：生成的 SQL 执行结果 vs 官方标准答案
（列式 JSON 转行集，数值按 2 位小数容差），多答案题命中任一即正确。

用法（项目 venv，cwd=项目根）：
        .venv\\Scripts\\python.exe benchmark\\run_eval.py --questions benchmark\\questions\\questions_falcon.jsonl
        # 断点续跑：同一 --out 再次执行即自动跳过已完成题目
        # 只汇总不跑：--report-only
        # 离线重标注：--relabel-quota 把历史 HTTPError:500 记录改为 model_quota_paused
        # 续费后重跑被标记题：--retry-status model_quota_paused,rate_limited
    """
import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_URL = os.environ.get("QF_BASE_URL", "http://localhost:8888")
USERNAME = os.environ.get("QF_USER", "admin")
PASSWORD = os.environ.get("QF_PASSWORD", "REDACTED")

# 与服务端 LIMIT_HEAVY(10/minute) 对齐的客户端节流：滚动窗口内最多 8 次创建
RATE_MAX_CALLS = 8
RATE_WINDOW = 60.0

NUM_TOL = 0.011  # 标准答案按 2 位小数舍入，浮点比较容差
MAX_ROWS = 2000  # 服务端 SQL_MAX_ROWS（系统设置，与 sql_executor 保持一致）

_print_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate_ts = []


def log(msg):
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def rate_gate():
    """滚动窗口限流：不够配额时等待。"""
    while True:
        with _rate_lock:
            now = time.time()
            while _rate_ts and now - _rate_ts[0] > RATE_WINDOW:
                _rate_ts.pop(0)
            if len(_rate_ts) < RATE_MAX_CALLS:
                _rate_ts.append(now)
                return
            wait = RATE_WINDOW - (now - _rate_ts[0]) + 0.5
        time.sleep(max(wait, 1.0))


# 模型配额类错误关键词（火山方舟 SetLimitExceeded / 未开通 / 欠费 / 通用 quota）
QUOTA_MARKERS = ("setlimitexceeded", "modelnotopen", "arrearage",
                 "usage limit", "quota", "欠费", "余额不足")


def classify_quota_error(resp_text):
    """判断响应体是否属于模型过期/配额不足类错误。"""
    low = (resp_text or "").lower()
    return any(m in low for m in QUOTA_MARKERS)


def login(session):
    r = session.post(f"{BASE_URL}/login",
                     json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    log(f"登录成功 user={USERNAME}")


# ---------------- 结果比对 ----------------

def _norm_cell(v):
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("num", float(v))
    if isinstance(v, (int, float)):
        return ("num", round(float(v), 6))
    s = str(v).strip()
    if not s:
        return ("str", "")
    try:
        return ("num", round(float(s), 6))
    except ValueError:
        return ("str", s)


def _norm_cell_tol(v):
    """带容差版本：数值保留原值用于 abs 差比较。"""
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("num", float(v))
    if isinstance(v, (int, float)):
        return ("num", float(v))
    s = str(v).strip()
    if not s:
        return ("str", "")
    try:
        return ("num", float(s))
    except ValueError:
        return ("str", s)


def _norm_rows(rows, col_count, tol=False):
    fn = _norm_cell_tol if tol else _norm_cell
    out = []
    for r in rows:
        cells = list(r)
        if len(cells) < col_count:
            cells = cells + [None] * (col_count - len(cells))
        out.append(tuple(fn(c) for c in cells[:col_count]))
    return out


def _rows_equal_tol(pred_rows, gold_rows):
    """逐位置比较，数值 |a-b|<=NUM_TOL 视为相等。"""
    if len(pred_rows) != len(gold_rows):
        return False
    for pr, gr in zip(pred_rows, gold_rows):
        if len(pr) != len(gr):
            return False
        for pv, gv in zip(pr, gr):
            if pv[0] != gv[0]:
                return False
            if pv[0] == "num" and abs(pv[1] - gv[1]) > NUM_TOL:
                return False
            if pv[0] != "num" and pv[1] != gv[1]:
                return False
    return True


def _ci(norm_rows):
    """大小写不敏感视图：字符串单元格转小写（用于回退比对层）。"""
    return [tuple((c[0], c[1].lower()) if c[0] == "str" else c for c in row)
            for row in norm_rows]


def _multiset_ok(pred, gold, ci=False):
    if ci:
        pred, gold = _ci(pred), _ci(gold)
    return len(pred) == len(gold) and Counter(pred) == Counter(gold)


def _permute(pred, idx_seq):
    return [tuple(pred[i] for i in idx_seq) for pred in pred]


def _unordered_match(pred, gold):
    """无序题分层比对，返回 (ex, note)。

    第 1 层：多重集（行序无关，列位置对齐）；
    第 2 层：字符串大小写不敏感多重集；
    第 3 层：列排列/多余列剔除（gold 列数的列子集排列），应对
             SELECT 多输出列、列顺序不同导致的错位（如 qid0）。
    """
    if _multiset_ok(pred, gold):
        return 1, "multiset"
    if _multiset_ok(pred, gold, ci=True):
        return 1, "multiset_ci"
    gcols = len(gold[0])
    pcols = len(pred[0])
    import itertools
    if pcols == gcols:
        idx_seqs = list(itertools.permutations(range(pcols)))
    elif pcols > gcols:
        idx_seqs = list(itertools.permutations(range(pcols), gcols))
    else:
        return 0, "value_mismatch"
    # 候选排列过多（>5040）时放弃列排列层，避免组合爆炸
    if len(idx_seqs) > 5040:
        return 0, "value_mismatch"
    # 排列去重（重复列时排列数会重复）
    seen = set()
    for seq in idx_seqs:
        if seq in seen:
            continue
        seen.add(seq)
        pp = _permute(pred, seq)
        if _multiset_ok(pp, gold):
            return 1, "multiset_perm"
        if _multiset_ok(pp, gold, ci=True):
            return 1, "multiset_perm_ci"
    return 0, "value_mismatch"


def compare_result(pred_rows, gold_rows, ordered):
    """返回 (ex, note)。gold_rows 为官方标准答案行集之一。

    ordered：is_order=1 的题逐位置比较（含前缀截断）；
    无序题做分层多重集比较：忽略行序 → 忽略字符串大小写 →
    忽略列顺序/多余输出列（评测口径：忽略列名与行序，要求排序除外）。
    """
    if pred_rows is None or gold_rows is None:
        return 0, "missing_rows"
    if not gold_rows and not pred_rows:
        return 1, "both_empty"
    if not gold_rows or not pred_rows:
        return 0, "empty_mismatch"
    col_count = len(gold_rows[0])
    if ordered:
        # 有序题沿用原口径：pred 截断到 gold 列宽后逐位置比较
        pred = _norm_rows(pred_rows, col_count, tol=True)
        gold = _norm_rows(gold_rows, col_count, tol=True)
        ok = _rows_equal_tol(pred[:len(gold)], gold) and len(pred) >= len(gold)
        return (1, "ordered") if ok else (0, "value_mismatch")
    # 无序题保留 pred 全部列（多余列交给列排列层处理）
    pred_width = max(len(r) for r in pred_rows)
    pred = _norm_rows(pred_rows, pred_width, tol=True)
    gold = _norm_rows(gold_rows, col_count, tol=True)
    return _unordered_match(pred, gold)


# ---------------- 单题评测 ----------------

# 触发备用模型切换的状态（超时/限流/配额暂停/服务端 500）
FALLBACK_STATUSES = {"timeout", "rate_limited", "model_quota_paused", "error"}


def eval_one_once(session, item, llm_config_id, http_timeout):
    qid = item["qid"]
    t0 = time.time()
    rec = {"qid": qid, "schema": item["schema"], "question": item["question"],
           "status": "error", "ex": 0, "note": ""}
    try:
        rate_gate()
        r = session.post(
            f"{BASE_URL}/api/conversation",
            json={"query": item["question"], "schema_name": item["schema"],
                  "db_type": "mysql", "llm_config_id": llm_config_id},
            timeout=http_timeout,
        )
        rec["latency_s"] = round(time.time() - t0, 1)
        if r.status_code == 429:
            rec["status"] = "rate_limited"
            rec["note"] = "服务端限流 429"
            return rec
        r.raise_for_status()
        data = r.json()
        msg = data.get("message") or {}
        rec["conversation_id"] = (data.get("conversation") or {}).get("id")
        rec["tokens"] = msg.get("tokens")
        rec["sql"] = msg.get("sql")

        if msg.get("need_more_info"):
            rec["status"] = "need_more_info"
            rec["note"] = "系统判定信息不足: " + json.dumps(
                msg.get("missing_info") or [], ensure_ascii=False)[:200]
            return rec
        if not msg.get("is_valid"):
            rec["status"] = "invalid_sql"
            rec["note"] = (msg.get("error_message") or "SQL 校验未通过")[:200]
            return rec

        qr = msg.get("query_result") or {}
        if qr.get("error"):
            rec["status"] = "exec_error"
            rec["note"] = str(qr.get("error"))[:200]
            return rec
        pred_rows = qr.get("rows") or []

        answers = item.get("answers") or []
        max_rows_ans = max((len(a) for a in answers), default=0)
        if max_rows_ans > MAX_ROWS:
            rec["note"] = f"标准答案 {max_rows_ans} 行超服务端 max_rows={MAX_ROWS} 截断"
            if not item.get("is_order"):
                rec["status"] = "row_limit"
                return rec
            answers = [a[:MAX_ROWS] for a in answers]
            pred_rows = pred_rows[:MAX_ROWS]

        best_note = "value_mismatch"
        for ans in answers:
            ex, note = compare_result(pred_rows, ans, bool(item.get("is_order")))
            if ex == 1:
                rec["ex"] = 1
                rec["status"] = "ok"
                rec["note"] = note
                return rec
            best_note = note
        rec["status"] = "wrong_answer"
        rec["note"] = f"{best_note} (pred {len(pred_rows)} 行 vs 标准答案 {max_rows_ans} 行)"
        return rec
    except requests.Timeout:
        rec["status"] = "timeout"
        rec["note"] = f"客户端超时({http_timeout}s)"
        return rec
    except requests.HTTPError as e:
        body = ""
        if e.response is not None:
            body = e.response.text or ""
        if classify_quota_error(body):
            rec["status"] = "model_quota_paused"
            rec["note"] = "模型过期/配额不足: " + body[:180]
        else:
            rec["status"] = "error"
            rec["note"] = f"{type(e).__name__}: {e}"[:200]
        return rec
    except Exception as e:
        rec["note"] = f"{type(e).__name__}: {e}"[:200]
        return rec


def eval_one(session, item, llm_config_id, http_timeout, fallback_ids=()):
    """单题评测，主配置命中超时/限流/配额/500 时依次用备用配置重试。"""
    rec = eval_one_once(session, item, llm_config_id, http_timeout)
    rec["llm_config_id"] = llm_config_id
    if rec["status"] in FALLBACK_STATUSES and fallback_ids:
        for fid in fallback_ids:
            if fid == llm_config_id:
                continue
            log(f"qid {item['qid']} [{rec['status']}] → 切换 llm_config_id={fid} 重试")
            rec = eval_one_once(session, item, fid, http_timeout)
            rec["llm_config_id"] = fid
            rec["fallback_from"] = llm_config_id
            if rec["status"] not in FALLBACK_STATUSES:
                break
    return rec


# ---------------- 汇总 ----------------

def summarize(records):
    total = len(records)
    ex_sum = sum(r.get("ex", 0) for r in records)
    buckets = Counter(r.get("status") for r in records)
    lat = [r["latency_s"] for r in records if r.get("latency_s")]
    tokens_in = sum((r.get("tokens") or {}).get("prompt_tokens", 0) or 0 for r in records)
    tokens_out = sum((r.get("tokens") or {}).get("completion_tokens", 0) or 0 for r in records)
    return {
        "total": total,
        "EX": round(ex_sum / total, 4) if total else 0.0,
        "EX_correct": ex_sum,
        "status_buckets": dict(buckets),
        "avg_latency_s": round(sum(lat) / len(lat), 1) if lat else None,
        "tokens_total": {"prompt": tokens_in, "completion": tokens_out},
    }


def load_records(out_path):
    """读取结果 JSONL，同 qid 保留最后一条（支持 --retry-status 覆盖旧记录）。"""
    by_qid = {}
    order = []
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("qid") not in by_qid:
                order.append(r.get("qid"))
            by_qid[r.get("qid")] = r
    return [by_qid[q] for q in order]


def relabel_quota(out_path):
    """离线重标注：历史 status=error 且 note 含 HTTPError:500 的记录改为
    model_quota_paused（依据服务端日志证据：该批次 500 均为 SetLimitExceeded）。"""
    recs = []
    n = 0
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            note = r.get("note") or ""
            if r.get("status") == "error" and "HTTPError" in note and "500" in note:
                r["status"] = "model_quota_paused"
                r["note"] = "模型过期/配额不足(离线标注): " + note[:160]
                n += 1
            recs.append(r)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log(f"离线重标注 {n}/{len(recs)} 条 → model_quota_paused")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="题目 JSONL 路径")
    ap.add_argument("--llm-config-id", type=int, default=4)
    ap.add_argument("--fallback-llm-ids", default="",
                    help="逗号分隔备用 llm_config_id，主配置超时/限流/配额/500 时依次切换重试（如 8,6）")
    ap.add_argument("--out", default=None, help="结果 JSONL 路径（默认 results/<题集名>.<config>.jsonl）")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全量）")
    ap.add_argument("--offset", type=int, default=0, help="跳过前 N 题后再取 limit（用于分段跑）")
    ap.add_argument("--http-timeout", type=int, default=600)
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--relabel-quota", action="store_true",
                    help="只离线重标注：把历史 HTTPError:500 记录改为 model_quota_paused")
    ap.add_argument("--retry-status", default="",
                    help="逗号分隔状态列表，这些状态的已完成记录视为待重跑（如 model_quota_paused,rate_limited）")
    args = ap.parse_args()

    name = os.path.splitext(os.path.basename(args.questions))[0]
    os.makedirs("benchmark/results", exist_ok=True)
    out_path = args.out or f"benchmark/results/{name}.c{args.llm_config_id}.jsonl"
    report_path = out_path.rsplit(".", 1)[0] + ".report.md"

    if args.relabel_quota:
        relabel_quota(out_path)
        args.report_only = True

    retry_statuses = {s.strip() for s in args.retry_status.split(",") if s.strip()}

    done_status = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        done_status[r["qid"]] = r.get("status")
                    except Exception:
                        pass

    with open(args.questions, encoding="utf-8") as f:
        items = [json.loads(l) for l in f if l.strip()]
    if args.offset:
        items = items[args.offset:]
    if args.limit:
        items = items[:args.limit]
    todo = [it for it in items
            if it["qid"] not in done_status or done_status[it["qid"]] in retry_statuses]
    log(f"题目 {len(items)}，已完成 {len(done_status)}，待跑 {len(todo)} → {out_path}"
        + (f"（重试状态: {','.join(retry_statuses)}）" if retry_statuses else ""))

    if not args.report_only:
        session = requests.Session()
        login(session)
        out_lock = threading.Lock()
        with open(out_path, "a", encoding="utf-8") as fout:
            def persist(rec):
                with out_lock:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                fids = tuple(int(x) for x in args.fallback_llm_ids.split(",") if x.strip())
                futs = {pool.submit(eval_one, session, it,
                                    args.llm_config_id, args.http_timeout, fids): it
                        for it in todo}
                n = 0
                for fut in as_completed(futs):
                    rec = fut.result()
                    persist(rec)
                    n += 1
                    log(f"({n}/{len(todo)}) {rec['qid']} [{rec['status']}] "
                        f"ex={rec.get('ex')} {rec.get('note','')[:80]}")

    records = load_records(out_path)
    summary = summarize(records)
    log("汇总: " + json.dumps(summary, ensure_ascii=False))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Baseline 评测汇总\n\n")
        f.write(f"- 题集: {name}  llm_config_id: {args.llm_config_id}\n")
        f.write(f"- 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- 题数: {summary['total']}  EX: {summary['EX']}"
                f" ({summary['EX_correct']}/{summary['total']})\n")
        f.write(f"- 状态分桶: {json.dumps(summary['status_buckets'], ensure_ascii=False)}\n")
        n_paused = summary["status_buckets"].get("model_quota_paused", 0)
        if n_paused:
            f.write(f"- ⚠ 模型过期/配额不足 {n_paused} 题（待续费后用 --retry-status model_quota_paused 重跑）\n")
        f.write(f"- 平均耗时: {summary['avg_latency_s']}s"
                f"  Token: {json.dumps(summary['tokens_total'])}\n\n")
        f.write("| qid | schema | status | EX | note |\n|---|---|---|---|---|\n")
        for r in records:
            f.write(f"| {r['qid']} | {r.get('schema')} | {r.get('status')} | "
                    f"{r.get('ex')} | {(r.get('note') or '').replace('|', '，')[:120]} |\n")
    log(f"报告: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
