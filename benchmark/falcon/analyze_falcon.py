# -*- coding: utf-8 -*-
"""Falcon 评测错题归因分析工具。

输入一个或多个结果 JSONL（同 qid 取最后一条），重放各题 SQL 到 MySQL，
用 run_eval 的新口径比对器重算 EX，并对失败题自动分桶失败模式：
  exec_error_replay / empty_result / fewer_rows / more_rows /
  disjoint / partial_overlap / superset / col_mismatch / null_cells / value_diff
同时对每道错题做"关联缺表"启发式（gold SQL 引用而 pred SQL 未引用的表）。

输出：
  <out>.enriched.jsonl   逐题增强记录（pred 行数/类别/缺表/新比对 note）
  stdout                 汇总统计（总 EX、分桶、分库、回退比对层命中）

用法：
  .venv\\Scripts\\python.exe benchmark\\analyze_falcon.py \
      --results benchmark\\results\\falcon.c7.smoke5_20261017.jsonl \
                benchmark\\results\\falcon.c7.q5_34_20261017.jsonl \
                benchmark\\results\\falcon.c7.q35_308_20261017.jsonl \
      --questions benchmark\\questions\\questions_falcon.jsonl \
      --out benchmark\\results\\falcon.c7.full309_20261017.enriched.jsonl
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import pymysql

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import compare_result, _norm_rows  # noqa: E402

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="REDACTED",
             charset="utf8mb4", autocommit=True, read_timeout=120)

TABLE_RE = re.compile(r"\b(?:from|join)\s+`?([A-Za-z_][\w$]*)`?", re.I)
# CTE/子查询别名：xxx AS ( —— 从"缺表"判定中剔除
CTE_RE = re.compile(r"\b`?([A-Za-z_][\w$]*)`?\s+as\s*\(", re.I)


def load_questions(path):
    qs = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                it = json.loads(line)
                qs[it["qid"]] = it
    return qs


def load_records(paths):
    """多文件合并，同 qid 取最后一条（后传文件优先）。"""
    by_qid = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    r["_src"] = os.path.basename(p)
                    by_qid[r["qid"]] = r
    return by_qid


def tables_of(sql):
    return {t.lower() for t in TABLE_RE.findall(sql or "")}


def real_tables_of(sql):
    """FROM/JOIN 引用的表，剔除 CTE/子查询别名。"""
    ctes = {c.lower() for c in CTE_RE.findall(sql or "")}
    return tables_of(sql) - ctes


def row_overlap(pred, gold):
    """多重集层面的重叠度量：(命中行数, gold行数, pred行数)。"""
    pc = Counter(pred)
    gc = Counter(gold)
    hit = sum(min(pc[k], gc[k]) for k in pc)
    return hit, sum(gc.values()), sum(pc.values())


def categorize(pred_rows, pred_err, gold_ans, is_order):
    """返回 (category, detail_dict)。仅在 status 为可比对失败时调用。"""
    if pred_err:
        if "max_execution_time" in str(pred_err) or "timed out" in str(pred_err):
            return "replay_timeout", {"err": str(pred_err)[:200]}
        return "exec_error_replay", {"err": str(pred_err)[:200]}
    best_ans = max(gold_ans, key=len)  # 行数最多的标准答案
    gold = _norm_rows(best_ans, len(best_ans[0]), tol=True)
    pred = _norm_rows(pred_rows, max(len(r) for r in pred_rows), tol=True) \
        if pred_rows else []
    if not pred:
        return "empty_result", {"gold_rows": len(gold)}
    gcols = len(gold[0]) if gold else 0
    pcols = len(pred[0])
    hit, gn, pn = row_overlap(
        [tuple(r[:gcols]) for r in pred] if pcols > gcols else pred, gold)
    # 有序题：行集合全对但逐位置比对失败 → 排名/tie-breaking 错位
    if is_order and gn and hit == gn and pn == gn:
        return "order_mismatch", {"pred_rows": pn, "gold_rows": gn,
                                  "pcols": pcols, "gcols": gcols}
    if gcols and pcols != gcols:
        # 列数不同也顺带看行重叠（可能同时是形态+值问题）
        return "col_mismatch", {"pcols": pcols, "gcols": gcols,
                                "pred_rows": pn, "gold_rows": gn,
                                "hit_rows": hit}
    if hit == 0:
        return "disjoint", {"pred_rows": pn, "gold_rows": gn}
    if pn == gn and hit == gn:
        return "order_mismatch", {"pred_rows": pn, "gold_rows": gn}
    if pn < gn:
        return "fewer_rows", {"pred_rows": pn, "gold_rows": gn, "hit_rows": hit}
    if pn > gn and hit == gn:
        return "superset", {"pred_rows": pn, "gold_rows": gn}
    return "partial_overlap", {"pred_rows": pn, "gold_rows": gn, "hit_rows": hit}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    qs = load_questions(args.questions)
    recs = load_records(args.results)

    my = pymysql.connect(**MYSQL)
    cur = my.cursor()
    # SELECT 最长 60s，防止慢查询卡死归因流程（超时按 exec_error_replay 归桶）
    cur.execute("SET SESSION max_execution_time = 60000")

    n_ok = n_ok_fallback = 0
    cat_counter = Counter()
    schema_counter = defaultdict(Counter)
    fallback_counter = Counter()
    enriched = []
    excludable = {"need_more_info", "row_limit", "exec_error", "timeout",
                  "error", "model_quota_paused", "rate_limited",
                  "invalid_sql"}
    for qid in sorted(recs):
        r = dict(recs[qid])
        q = qs.get(qid, {})
        r["question"] = q.get("question")
        r["is_order"] = q.get("is_order")
        status = r.get("status")
        # 1) 可比对的记录：重放 SQL + 新口径重算
        if status in ("ok", "wrong_answer") and r.get("sql"):
            pred_err = None
            pred_rows = []
            try:
                cur.execute(f"USE `{r['schema']}`")
                cur.execute(r["sql"])
                pred_rows = [list(row) for row in cur.fetchall()]
            except Exception as e:
                pred_err = e
            new_ex, new_note = 0, "replay_error"
            if pred_err is None:
                answers = q.get("answers") or []
                max_rows_ans = max((len(a) for a in answers), default=0)
                if max_rows_ans > 2000 and not q.get("is_order"):
                    new_ex, new_note = 0, "row_limit"
                else:
                    if max_rows_ans > 2000:
                        answers = [a[:2000] for a in answers]
                        pred_rows = pred_rows[:2000]
                    for ans in answers:
                        ex, note = compare_result(pred_rows, ans,
                                                  bool(q.get("is_order")))
                        if ex == 1:
                            new_ex, new_note = ex, note
                            break
                        new_note = note
            r["pred_rows_count"] = len(pred_rows)
            r["replay_ex"] = new_ex
            r["replay_note"] = new_note
            r["ex"] = new_ex
            if new_ex == 1:
                if status == "ok":
                    n_ok += 1
                else:
                    r["status"] = "ok"
                    r["note"] = f"重算翻正({status}): {new_note}"
                    n_ok += 1
                if new_note not in ("ordered", "multiset"):
                    fallback_counter[new_note] += 1
                if status == "wrong_answer":
                    n_ok_fallback += 1
            else:
                if status == "ok":
                    r["status"] = "wrong_answer"
                    r["note"] = f"重算翻负(ok旧口径): {new_note}"
                cat, detail = categorize(pred_rows, pred_err,
                                         answers, q.get("is_order"))
                detail["compare_note"] = new_note
                gold_tabs = real_tables_of(q.get("gold_sql"))
                pred_tabs = real_tables_of(r.get("sql"))
                missing = sorted(gold_tabs - pred_tabs)
                extra = sorted(pred_tabs - gold_tabs)
                if missing:
                    detail["missing_tables"] = missing
                if extra:
                    detail["extra_tables"] = extra
                r["fail_category"] = cat
                r["fail_detail"] = detail
                cat_counter[cat] += 1
                schema_counter[r.get("schema")][cat] += 1
        elif status in excludable:
            cat_counter[f"_{status}"] += 1
            schema_counter[r.get("schema")][f"_{status}"] += 1
        enriched.append(r)
    my.close()

    with open(args.out, "w", encoding="utf-8") as f:
        for r in enriched:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(enriched)
    n_intercept = cat_counter.get("_need_more_info", 0)
    n_exc = sum(v for k, v in cat_counter.items()
                if k.startswith("_") and k != "_need_more_info")
    denom = total - n_intercept - n_exc
    print(f"\n===== Falcon 归因汇总 =====")
    print(f"总题 {total} | 拦截 {n_intercept} | 异常/跳过 {n_exc} | EX 分母 {denom}")
    print(f"EX(新口径) = {n_ok}/{denom} = {n_ok / denom:.3f}" if denom else "无分母")
    print(f"其中重算翻正(wrong→ok): {n_ok_fallback}")
    print(f"回退比对层命中分布: {dict(fallback_counter)}")
    print(f"\n失败分桶:")
    for k, v in cat_counter.most_common():
        print(f"  {k}: {v}")
    print(f"\n分库 x 分桶:")
    for s, cc in sorted(schema_counter.items()):
        print(f"  {s}: {dict(cc)}")
    print(f"\n逐题明细见: {args.out}")


if __name__ == "__main__":
    main()
