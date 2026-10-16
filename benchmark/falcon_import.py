# -*- coding: utf-8 -*-
"""Falcon dev 数据导入脚本（对应 docs/NL2SQL基准测试方案.md 第 3 节）。

两个功能：
1. --import：把 Falcon dev_data 的 16 个 SQLite 库导入本地 MySQL，
   每个源库一个 schema：falcon_dev_<db_id>（可重复执行，先 DROP 再建）；
2. --questions：生成 benchmark/questions/questions_falcon.jsonl 题目文件
   （qid/question/schema/is_order/answers，answers 已转为行集）。

数据源目录结构（--src，默认 benchmark/data/falcon，脚本所在目录同级）：
    dev.json / tables.json / dev_databases/<db_id>/<db_id>.sqlite

用法（项目 venv）：
    .venv\\Scripts\\python.exe benchmark\\falcon_import.py --import --questions
"""
import argparse
import json
import os
import sqlite3
import sys

import pymysql

DEFAULT_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "falcon")
MYSQL_CONF = dict(
    host=os.environ.get("QF_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("QF_MYSQL_PORT", "3306")),
    user=os.environ.get("QF_MYSQL_USER", "root"),
    password=os.environ.get("QF_MYSQL_PASSWORD", "REDACTED"),
    charset="utf8mb4",
    autocommit=True,
)

Q = "`"  # MySQL 标识符引用


def sql_type_to_mysql(decl):
    d = (decl or "").upper()
    if "INT" in d:
        return "BIGINT"
    if "REAL" in d or "FLOA" in d or "DOUB" in d or "NUM" in d or "DEC" in d:
        return "DOUBLE"
    if "BLOB" in d:
        return "BLOB"
    return "TEXT"


def bq(name):
    return f"{Q}{name}{Q}"


def import_db(db_id, sqlite_path, conn):
    """把一个 SQLite 库导入 MySQL schema falcon_dev_<db_id>，返回表数与总行数。"""
    schema = f"falcon_dev_{db_id}"
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {bq(schema)}")
        cur.execute(
            f"CREATE DATABASE {bq(schema)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.text_factory = lambda b: b.decode("utf-8", errors="replace")
    try:
        cur = src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        n_tables = n_rows = 0
        for t in tables:
            cols = src.execute(f"PRAGMA table_info({bq(t)})").fetchall()
            # cols: cid, name, type, notnull, dflt_value, pk
            col_defs, pk_cols = [], []
            for _, name, decl, notnull, _dflt, pk in cols:
                col_defs.append(f"{bq(name)} {sql_type_to_mysql(decl)}")
                if pk:
                    pk_cols.append(name)
            ddl = (f"CREATE TABLE {bq(schema)}.{bq(t)} (\n  "
                   + ",\n  ".join(col_defs)
                   + (f",\n  PRIMARY KEY ({', '.join(bq(c) for c in pk_cols)})"
                      if pk_cols else "")
                   + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
            rows = src.execute(f"SELECT * FROM {bq(t)}").fetchall()
            with conn.cursor() as mc:
                mc.execute(f"USE {bq(schema)}")
                mc.execute(ddl)
                if rows:
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_list = ", ".join(bq(c[1]) for c in cols)
                    insert = f"INSERT INTO {bq(t)} ({col_list}) VALUES ({placeholders})"
                    clean = [
                        tuple(v.decode("utf-8", errors="replace")
                              if isinstance(v, bytes) else v for v in r)
                        for r in rows
                    ]
                    for i in range(0, len(clean), 500):
                        mc.executemany(insert, clean[i:i + 500])
            n_tables += 1
            n_rows += len(rows)
            print(f"  {schema}.{t}: {len(rows)} 行", flush=True)
        return n_tables, n_rows
    finally:
        src.close()


def do_import(src_dir):
    dev = json.load(open(os.path.join(src_dir, "dev.json"), encoding="utf-8"))
    db_ids = sorted({x["db_id"] for x in dev})
    conn = pymysql.connect(**MYSQL_CONF)
    try:
        for db_id in db_ids:
            sqlite_path = os.path.join(src_dir, "dev_databases", str(db_id),
                                       f"{db_id}.sqlite")
            if not os.path.exists(sqlite_path):
                print(f"!! 缺少 {sqlite_path}，跳过 db_id={db_id}")
                continue
            n_tables, n_rows = import_db(db_id, sqlite_path, conn)
            print(f"== db_id={db_id} → falcon_dev_{db_id}: {n_tables} 表 / {n_rows} 行", flush=True)
    finally:
        conn.close()
    print("导入完成")


def answer_to_rows(ans):
    """列式 answer（{col: [v...]}, 可能多列长度不齐）→ 行集列表。"""
    rows = []
    if not ans:
        return rows
    cols = list(ans.keys())
    length = max((len(ans[c]) for c in cols), default=0)
    for i in range(length):
        rows.append(tuple(ans[c][i] if i < len(ans[c]) else None for c in cols))
    return rows


def do_questions(src_dir, out_path):
    dev = json.load(open(os.path.join(src_dir, "dev.json"), encoding="utf-8"))
    dev.sort(key=lambda x: x["question_id"])
    items = []
    for x in dev:
        answers = [answer_to_rows(a) for a in x.get("answer") or []]
        items.append({
            "qid": x["question_id"],
            "schema": f"falcon_dev_{x['db_id']}",
            "question": x["question"],
            "is_order": int(x.get("is_order") or 0),
            "answers": answers,
            "gold_sql": (x.get("SQL") or [""])[0],  # MaxCompute 方言，仅供调试参考
        })
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    n_empty = sum(1 for it in items if not it["answers"])
    print(f"题目文件: {out_path} 共 {len(items)} 题（无答案 {n_empty} 题）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--import", dest="do_import", action="store_true")
    ap.add_argument("--questions", dest="do_questions", action="store_true")
    ap.add_argument("--out", default=os.path.join("benchmark", "questions", "questions_falcon.jsonl"))
    args = ap.parse_args()
    if not (args.do_import or args.do_questions):
        print("无操作：指定 --import 和/或 --questions")
        sys.exit(2)
    if args.do_questions:
        do_questions(args.src, args.out)
    if args.do_import:
        do_import(args.src)


if __name__ == "__main__":
    main()
