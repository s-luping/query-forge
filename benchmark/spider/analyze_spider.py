# -*- coding: utf-8 -*-
"""Spider 累计评测统一口径离线重算 + 失败分桶。

输入: 三轮结果文件（首轮10 / 增测30批(40) / 增测100），按 question_id 取最新记录
处理: 对每条有 gen_sql 的记录在 MySQL 重放生成 SQL，统一算 strict / wide(宽口径)，
      并做失败分桶（intercepted/exec_error/infra/tie_superset/wide_pass/true_wrong）
输出: benchmark/results/spider.cumulative_140.analysis.json
"""
import json
import os
from collections import Counter

import pymysql

import spider_bench as sb

BASE = os.path.dirname(os.path.abspath(__file__))

BATCHES = [
    ("c7.extra30", os.path.join(BASE, "..", "results", "spider",
                                "spider.c7.extra30_20261020.json")),
    ("c7.extra100", os.path.join(BASE, "..", "results", "spider",
                                 "spider.c7.extra100_20261020.json")),
]
QUESTIONS = [
    os.path.join(BASE, "..", "questions", "spider", "spider_selected.json"),
]
OUT = os.path.join(BASE, "..", "results", "spider", "spider.cumulative_140.analysis.json")


def replay(mysql_db, sql):
    my = pymysql.connect(database=mysql_db, host="127.0.0.1", port=3306,
                         user="root", password="REDACTED", charset="utf8mb4")
    try:
        with my.cursor() as c:
            c.execute("SET SESSION MAX_EXECUTION_TIME=60000")
            c.execute(sql)
            return c.fetchmany(sb.MAX_ROWS + 1)
    finally:
        my.close()


def bucket(rec, strict, wide_ok, gen_rows, gold_rows):
    if rec.get("error"):
        return "infra"
    if rec.get("need_more_info"):
        return "intercepted"
    if rec.get("exec_error"):
        return "exec_error"
    if strict:
        return "ok"
    if wide_ok:
        return "wide_pass"
    # 并列最值：gen 多重集 ⊇ gold 且行数更多
    if gen_rows and gold_rows:
        gset, sset = Counter(gen_rows), Counter(gold_rows)
        if len(gen_rows) > len(gold_rows) and not (sset - gset):
            return "tie_superset"
    return "true_wrong"


def main():
    last = {}
    for tag, path in BATCHES:
        with open(path, encoding="utf-8") as f:
            for r in json.load(f):
                r["_batch"] = tag
                last[r["question_id"]] = r
    questions = {}
    for p in QUESTIONS:
        with open(p, encoding="utf-8") as f:
            for q in json.load(f):
                questions[q["question_id"]] = q

    out = []
    for qid, rec in last.items():
        q = questions[qid]
        gen_rows = gold_rows = None
        strict = bool(rec.get("match"))
        wide_ok = bool(rec.get("match_wide"))
        layer = rec.get("wide_layer", "")
        if rec.get("gen_sql") and not rec.get("need_more_info"):
            try:
                rows = replay(q["mysql_db"], rec["gen_sql"])[:sb.MAX_ROWS]
                rows = [tuple(sb._jsonable(c) for c in r) for r in rows]  # Decimal→float
                gen_rows = sb.norm_rows(rows)
                gold_rows = sb.norm_rows(q["gold_result"])
                strict = (gen_rows == gold_rows)
                if not strict:
                    wide_ok, layer = sb.wide_compare(rows, q["gold_result"])
            except Exception as e:
                rec["replay_error"] = str(e)[:200]
        b = bucket(rec, strict, wide_ok, gen_rows, gold_rows)
        out.append({
            "question_id": qid, "dev_index": q["dev_index"], "db_id": q["db_id"],
            "question": q["question"], "gold_sql": q["gold_sql"],
            "gen_sql": rec.get("gen_sql"), "batch": rec.get("_batch"),
            "llm_config_id": rec.get("llm_config_id"),
            "strict": strict, "wide": wide_ok, "wide_layer": layer,
            "bucket": b, "elapsed_s": rec.get("elapsed_s"),
            "error": rec.get("error"), "exec_error": rec.get("exec_error"),
            "need_more_info": rec.get("need_more_info"),
            "missing_info": rec.get("missing_info"),
            "gen_rows": len(gen_rows) if gen_rows is not None else rec.get("gen_rows_count"),
            "gold_rows": len(gold_rows) if gold_rows is not None else rec.get("gold_rows_count"),
            "replay_error": rec.get("replay_error"),
        })
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    n = len(out)
    ok = sum(1 for r in out if r["bucket"] == "ok")
    wide_all = sum(1 for r in out if r["bucket"] in ("ok", "wide_pass"))
    print(f"累计 {n} 题 | 严格 EX {ok}/{n} = {ok/n*100:.1f}% | "
          f"宽口径 {wide_all}/{n} = {wide_all/n*100:.1f}%")
    for b, c in Counter(r["bucket"] for r in out).most_common():
        print(f"  {b}: {c}")
    print("\n失败题:")
    for r in out:
        if r["bucket"] not in ("ok",):
            print(f"  [{r['bucket']}] {r['question_id']} {r['db_id']} "
                  f"wide={r['wide']} layer={r['wide_layer']} gen={r['gen_rows']} gold={r['gold_rows']}")


if __name__ == "__main__":
    main()
