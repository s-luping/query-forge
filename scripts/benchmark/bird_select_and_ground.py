# -*- coding: utf-8 -*-
"""从 BIRD dev.json 选题、把 gold SQL 适配为 MySQL 方言并在 MySQL 上执行，
生成标准答案（ground truth），输出 selected_questions.json。

用法:
  python bird_select_and_ground.py <dev.json路径> <mysql库名>=<db_id> ... <输出json>
"""
import json
import re
import sys

import pymysql

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="REDACTED",
             charset="utf8mb4", autocommit=True)
PER_DB = {"simple": 3, "moderate": 3, "challenging": 2}
SEED = 42


def adapt_sql(sql: str) -> str:
    s = sql
    s = re.sub(r"\bIIF\s*\(", "IF(", s, flags=re.I)
    s = re.sub(r"CAST\s*\((.*?)\s+AS\s+REAL\)", r"CAST(\1 AS DOUBLE)", s, flags=re.I)
    # DATE(col, '-1 day') / DATE(col, '+3 days')
    def date_off(m):
        col, sign, n = m.group(1), m.group(2), m.group(3)
        fn = "DATE_SUB" if sign == "-" else "DATE_ADD"
        return f"{fn}({col}, INTERVAL {n} DAY)"
    s = re.sub(r"DATE\s*\(\s*([^,()]+?)\s*,\s*'([+-])\s*(\d+)\s*days?'\)",
               date_off, s, flags=re.I)
    # STRFTIME(fmt, x) -> DATE_FORMAT(x, fmt')，嵌套时由内向外多轮替换
    def fmt_conv(m):
        fmt, x = m.group(1), m.group(2)
        fmt = fmt.replace("%M", "%i").replace("%f", "%f")
        return f"DATE_FORMAT({x}, {fmt})"
    for _ in range(6):
        new = re.sub(r"STRFTIME\s*\(\s*('[^']*')\s*,\s*((?:[^'()]|\([^()]*\))*?)\)",
                     fmt_conv, s, flags=re.I)
        if new == s:
            break
        s = new
    return s


def norm_cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{round(v, 4):.4f}"
    return str(v).strip()


def try_execute(mc, sql):
    """执行成功返回规范化结果集(排序后)，失败返回 None"""
    try:
        mc.execute(sql)
        rows = mc.fetchall()
        return sorted(tuple(norm_cell(c) for c in r) for r in rows)
    except Exception:
        return None


def main(dev_json, db_args, out_path):
    with open(dev_json, encoding="utf-8") as f:
        all_items = json.load(f)
    my = pymysql.connect(**MYSQL)
    mc = my.cursor()
    selected = []
    import random
    for arg in db_args:
        mysql_db, db_id = arg.split("=", 1)
        mc.execute(f"USE `{mysql_db}`")
        items = [d for d in all_items if d["db_id"] == db_id]
        random.seed(SEED)
        buckets = {}
        skipped_dialect = 0
        for d in items:
            adapted = adapt_sql(d["SQL"])
            gt = try_execute(mc, adapted)
            if gt is None and try_execute(mc, d["SQL"]) is None:
                skipped_dialect += 1
                continue
            buckets.setdefault(d["difficulty"], []).append((d, adapted, gt))
        print(f"[{db_id}] 可执行候选: " +
              ", ".join(f"{k}={len(v)}" for k, v in buckets.items()) +
              f", 方言不可执行跳过: {skipped_dialect}")
        for diff, n in PER_DB.items():
            pool = buckets.get(diff, [])
            random.shuffle(pool)
            # 优先选结果集非空且不太大的题目
            pool.sort(key=lambda x: (len(x[2]) == 0, len(x[2])))
            for d, adapted, gt in pool[:n]:
                selected.append({
                    "question_id": d["question_id"], "db_id": db_id,
                    "mysql_db": mysql_db, "difficulty": diff,
                    "question": d["question"], "evidence": d.get("evidence", ""),
                    "gold_sql": d["SQL"], "adapted_gold_mysql": adapted,
                    "gold_rows_count": len(gt), "gold_result": gt[:200],
                })
    my.close()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=1)
    print(f"共选出 {len(selected)} 题 -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:-1], sys.argv[-1])
