# -*- coding: utf-8 -*-
"""离线重算 qf_results.json 的 match 字段：
直接在 MySQL 上执行每题的 gen_sql，与 gold_result 规范化比对。
可重复执行（幂等），用于修正客户端比对 bug 或服务端执行缓存差异。
"""
import json

import pymysql

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="REDACTED",
             charset="utf8mb4", autocommit=True)
SRC = r"D:\qf_bench\qf_results.json"


def norm_cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{round(v, 4):.4f}"
    return str(v).strip()


def main():
    with open(SRC, encoding="utf-8") as f:
        rs = json.load(f)
    my = pymysql.connect(**MYSQL)
    mc = my.cursor()
    for r in rs:
        sql = r.get("gen_sql")
        if not sql:
            continue
        try:
            mc.execute(f"USE `{r['mysql_db']}`")
            mc.execute(sql)
            rows = mc.fetchall()
            gen = sorted(tuple(norm_cell(c) for c in row) for row in rows)
            r["exec_error"] = None
            r["gen_rows_count"] = len(gen)
            gold = sorted(tuple(norm_cell(c) for c in row) for row in r["gold_result"])
            r["match"] = (gen == gold)
        except Exception as e:
            r["exec_error"] = str(e)[:300]
            r["match"] = False
    my.close()
    with open(SRC, "w", encoding="utf-8") as f:
        json.dump(rs, f, ensure_ascii=False, indent=1)
    n = len(rs)
    ok = sum(1 for r in rs if r["match"])
    print(f"recomputed: {ok}/{n}")


if __name__ == "__main__":
    main()
