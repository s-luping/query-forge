# -*- coding: utf-8 -*-
"""将 BIRD dev 的 SQLite 库导入本地 MySQL（建表含注释/主键/外键 + 全量数据）。

用法:
  python bird_to_mysql.py <sqlite_path> <mysql_db_name> <desc_csv_dir>

desc_csv_dir 为 BIRD database_description/<db_name> 目录，内含每表一个 CSV
(列说明)，用于生成 MySQL 列 COMMENT，供 QF 同步后提升字段召回质量。
"""
import csv
import os
import sqlite3
import sys

import pymysql

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="REDACTED",
             charset="utf8mb4", autocommit=True)


def type_map(sqlite_type: str) -> str:
    t = (sqlite_type or "").upper()
    if "INT" in t:
        return "BIGINT"
    if any(k in t for k in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
        return "DOUBLE"
    if "BLOB" in t or not t:
        return "TEXT"
    return "TEXT"


def load_comments(desc_dir, table):
    """返回 {column_name_lower: description}"""
    path = os.path.join(desc_dir, table + ".csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if len(rows) < 2:
        return out
    header = [h.strip().lower() for h in rows[0]]
    # 常见表头: original_column_name,column_name,column_description,... 或 name,description
    def idx(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return -1
    i_name = idx("original_column_name", "column_name", "name", "field")
    i_desc = idx("column_description", "description", "desc", "comment")
    i_nl = idx("column_name")
    i_val = idx("value_description")
    if i_name < 0 or i_desc < 0:
        return out
    for row in rows[1:]:
        if len(row) > max(i_name, i_desc):
            name = row[i_name].strip().strip('"').lower()
            parts = []
            if i_nl >= 0 and len(row) > i_nl and row[i_nl].strip():
                parts.append(row[i_nl].strip())
            if row[i_desc].strip():
                parts.append(row[i_desc].strip())
            if i_val >= 0 and len(row) > i_val and row[i_val].strip():
                parts.append("values: " + row[i_val].strip())
            desc = " | ".join(parts)
            if name and desc:
                out[name] = desc[:250]  # MySQL comment 上限保护
    return out


def main(sqlite_path, db_name, desc_dir):
    con = sqlite3.connect(sqlite_path)
    con.text_factory = lambda b: b.decode("utf-8", "ignore")
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    print(f"[{db_name}] tables: {tables}")

    my = pymysql.connect(database=None, **MYSQL)
    mc = my.cursor()
    mc.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
    mc.execute(f"CREATE DATABASE `{db_name}` DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci")
    mc.execute(f"USE `{db_name}`")
    # 建表阶段也需关闭外键检查（允许引用尚未创建的表）
    mc.execute("SET FOREIGN_KEY_CHECKS=0")

    # 建表
    for t in tables:
        info = cur.execute(f"PRAGMA table_info('{t}')").fetchall()
        cols, pks = [], []
        for cid, name, ctype, notnull, dflt, pk in info:
            mysql_type = type_map(ctype)
            comment = ""
            cm = load_comments(desc_dir, t)
            if name.lower() in cm:
                comment = " COMMENT '" + cm[name.lower()].replace("'", "''") + "'"
            part = f"  `{name}` {mysql_type}"
            if notnull or pk:
                part += " NOT NULL"
            part += comment
            cols.append(part)
            if pk:
                pks.append(name)
        ddl = f"CREATE TABLE `{t}` (\n" + ",\n".join(cols)
        if pks:
            ddl += ",\n  PRIMARY KEY (" + ", ".join(f"`{p}`" for p in pks) + ")"
        # 外键
        fks = cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
        by_id = {}
        for f in fks:
            fid, rtable, frm, to = f[0], f[2], f[3], f[4]
            by_id.setdefault(fid, {"table": rtable, "pairs": []})["pairs"].append((frm, to))
        for fid, fk in sorted(by_id.items()):
            pairs = ", ".join(f"`{a}`" for a, _ in fk["pairs"])
            rpairs = ", ".join(f"`{b}`" for _, b in fk["pairs"])
            ddl += (f",\n  CONSTRAINT `fk_{t}_{fid}` FOREIGN KEY ({pairs}) "
                    f"REFERENCES `{fk['table']}` ({rpairs})")
        ddl += "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        try:
            mc.execute(ddl)
        except Exception as e:
            print(f"  [WARN] create {t} failed: {e}\n{ddl}")
            continue

    # 导数据（关外键检查，按建表顺序）
    mc.execute("SET FOREIGN_KEY_CHECKS=0")
    for t in tables:
        rows = cur.execute(f"SELECT * FROM '{t}'").fetchall()
        if not rows:
            print(f"  {t}: 0 rows")
            continue
        n = len(rows[0])
        ph = ",".join(["%s"] * n)
        sql = f"INSERT INTO `{t}` VALUES ({ph})"
        for i in range(0, len(rows), 500):
            batch = [tuple(bytes(v) if isinstance(v, memoryview) else v for v in r)
                     for r in rows[i:i + 500]]
            try:
                mc.executemany(sql, batch)
            except Exception as e:
                print(f"  [WARN] insert {t} batch {i}: {e}")
        print(f"  {t}: {len(rows)} rows")

    mc.execute("SET FOREIGN_KEY_CHECKS=1")
    my.close()
    con.close()
    print(f"[{db_name}] done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
