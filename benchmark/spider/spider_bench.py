# -*- coding: utf-8 -*-
"""QueryForge × Spider 1.0 (dev) 基准测试驱动。

数据源: ModelScope ModelM/spider（官方 spider.zip + dev.json + dev_gold.sql + tables.json）
已解压至 benchmark/data/spider/spider/{database,dev.json,dev_gold.sql,tables.json}

用法（.venv\Scripts\python.exe benchmark\spider_bench.py <cmd> ...）:
  import <db_id> [db_id...]      # 导入 spider SQLite 库到 MySQL spider_<db_id>
  select [N]                     # 确定性抽题（默认 10）：按 dev.json 首现库序逐库
                                 # 导入并验证 gold SQL 可在 MySQL 执行，每库取第一条通过题
  setup                          # 建 QF 数据源→同步任务→执行→重建向量索引
  test <questions_json> <out_json> [llm_config_id]
                                 # 逐题调 QF NL2SQL 并与 gold 结果集比对
"""
import json
import os
import sqlite3
import sys
import threading
import time

import pymysql
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # benchmark/spider/
SPIDER_DIR = os.path.join(BASE_DIR, "..", "data", "spider", "spider")
DB_DIR = os.path.join(SPIDER_DIR, "database")
QUESTIONS_DIR = os.path.join(BASE_DIR, "..", "questions", "spider")
RESULTS_DIR = os.path.join(BASE_DIR, "..", "results", "spider")

MYSQL = dict(host="127.0.0.1", port=3306, user="root",
             password=os.environ.get("QF_MYSQL_PASSWORD", ""),
             charset="utf8mb4", autocommit=True)
BASE_URL = "http://localhost:8888"
USER, PWD = "admin", os.environ.get("QF_PASSWORD", "")
MAX_ROWS = 2000
SESSION = requests.Session()  # 仅单线程路径使用；多线程走 _tls 线程本地会话
_tls = threading.local()
TIMEOUT = 600


def _session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        _tls.s = s
    return s


# ---------------------------------------------------------------- MySQL 导入

def type_map(sqlite_type: str, is_key: bool = False) -> str:
    t = (sqlite_type or "").upper()
    if "INT" in t:
        return "BIGINT"
    if any(k in t for k in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
        return "DOUBLE"
    if is_key or not t:
        # SQLite 无类型声明的列：做键（主/外键）必须给可索引类型
        return "VARCHAR(255)"
    return "TEXT"


def import_db(db_id, mysql_db=None, skip_if_exists=True):
    mysql_db = mysql_db or f"spider_{db_id}"
    my = pymysql.connect(database=None, **MYSQL)
    mc = my.cursor()
    if skip_if_exists:
        mc.execute("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                   (mysql_db,))
        if mc.fetchone()[0]:
            n = mc.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (mysql_db,))
            n = mc.fetchone()[0]
            print(f"[{db_id}] {mysql_db} 已存在（{n} 表），跳过导入", flush=True)
            my.close()
            return mysql_db
    con = sqlite3.connect(os.path.join(DB_DIR, db_id, f"{db_id}.sqlite"))
    con.text_factory = lambda b: b.decode("utf-8", "ignore")
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    print(f"[{db_id}] tables: {tables}", flush=True)

    # 预扫描键列：主键 + 外键本地列 + 被引用列
    key_cols = {t: set() for t in tables}
    table_info = {}
    for t in tables:
        table_info[t] = cur.execute(f"PRAGMA table_info('{t}')").fetchall()
        for cid, name, ctype, notnull, dflt, pk in table_info[t]:
            if pk:
                key_cols[t].add(name)
        for f in cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall():
            fid, rtable, frm, to = f[0], f[2], f[3], f[4]
            key_cols[t].add(frm)
            if rtable in key_cols:
                key_cols[rtable].add(to)

    my = pymysql.connect(database=None, **MYSQL)
    mc = my.cursor()
    mc.execute(f"DROP DATABASE IF EXISTS `{mysql_db}`")
    mc.execute(f"CREATE DATABASE `{mysql_db}` DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci")
    mc.execute(f"USE `{mysql_db}`")
    mc.execute("SET FOREIGN_KEY_CHECKS=0")

    # 第一遍：定类型。FK 本地列类型跟随被引用列（Spider gold schema 常见两端不一致），
    # 无类型声明的键列用 VARCHAR(255)
    col_types = {t: {} for t in tables}
    for t in tables:
        for cid, name, ctype, notnull, dflt, pk in table_info[t]:
            col_types[t][name] = type_map(ctype, is_key=name in key_cols[t])
    fk_index_needed = set()  # 非主键的被引用列 (table, col) 需补索引
    for t in tables:
        for f in cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall():
            fid, rtable, frm, to = f[0], f[2], f[3], f[4]
            if rtable in col_types and to in col_types[rtable] and frm in col_types[t]:
                col_types[t][frm] = col_types[rtable][to]
            pk_cols = {name for cid, name, ctype, notnull, dflt, pk in table_info.get(rtable, [])
                       if pk}
            if rtable in col_types and to not in pk_cols:
                fk_index_needed.add((rtable, to))

    # 第二遍：建表
    for t in tables:
        cols, pks = [], []
        for cid, name, ctype, notnull, dflt, pk in table_info[t]:
            mysql_type = col_types[t][name]
            part = f"  `{name}` {mysql_type}"
            if notnull or pk:
                part += " NOT NULL"
            cols.append(part)
            if pk:
                pks.append(name)
        ddl = f"CREATE TABLE `{t}` (\n" + ",\n".join(cols)
        if pks:
            ddl += ",\n  PRIMARY KEY (" + ", ".join(f"`{p}`" for p in pks) + ")"
        # 被引用的非主键列内联建索引（MySQL 建 FK 时被引用列必须已有索引）
        for (rt, rc) in sorted(fk_index_needed):
            if rt == t:
                ddl += f",\n  INDEX `idx_{rt}_{rc}` (`{rc}`)"
        fks = cur.execute(f"PRAGMA foreign_key_list('{t}')").fetchall()
        by_id = {}
        seen_fk_pairs = set()  # SQLite 源可能重复声明同一外键（如 dog_kennels dogs.owner_id）
        for f in fks:
            fid, rtable, frm, to = f[0], f[2], f[3], f[4]
            pair = (rtable, frm, to)
            if pair in seen_fk_pairs:
                continue
            seen_fk_pairs.add(pair)
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
            print(f"  [WARN] create {t} failed: {e}", flush=True)
            continue
    # 非主键被引用列补索引（MySQL 要求被引用列有索引，如 model_list.Model UNIQUE）
    for (rt, rc) in sorted(fk_index_needed):
        try:
            mc.execute(f"ALTER TABLE `{rt}` ADD INDEX `idx_{rt}_{rc}` (`{rc}`)")
        except Exception as e:
            print(f"  [WARN] index {rt}.{rc}: {e}", flush=True)
    mc.execute("SET FOREIGN_KEY_CHECKS=0")
    for t in tables:
        try:
            rows = cur.execute(f"SELECT * FROM '{t}'").fetchall()
        except Exception as e:
            print(f"  [WARN] read {t}: {e}", flush=True)
            continue
        if not rows:
            print(f"  {t}: 0 rows", flush=True)
            continue
        ph = ",".join(["%s"] * len(rows[0]))
        sql = f"INSERT INTO `{t}` VALUES ({ph})"
        # BIGINT 列的空串/非数字串转 NULL（SQLite 弱类型脏值）
        int_idx = [i for i, (cid, name, *_rest) in enumerate(table_info[t])
                   if col_types[t].get(name) == "BIGINT"]

        def coerce(r):
            r = list(r)
            for i in int_idx:
                if isinstance(r[i], str):
                    try:
                        r[i] = int(float(r[i])) if r[i].strip() != "" else None
                    except ValueError:
                        r[i] = None
            return tuple(bytes(v) if isinstance(v, memoryview) else v for v in r)

        for i in range(0, len(rows), 500):
            batch = [coerce(r) for r in rows[i:i + 500]]
            try:
                mc.executemany(sql, batch)
            except Exception as e:
                print(f"  [WARN] insert {t} batch {i}: {e}", flush=True)
        print(f"  {t}: {len(rows)} rows", flush=True)
    my.close()
    con.close()
    print(f"[{db_id}] done -> {mysql_db}", flush=True)
    return mysql_db


# ---------------------------------------------------------------- 抽题

def load_dev():
    with open(os.path.join(SPIDER_DIR, "dev.json"), encoding="utf-8") as f:
        dev = json.load(f)
    # dev_gold.sql 按行序与 dev.json 一一对应: <gold SQL>\t<db_id>
    golds = []
    with open(os.path.join(SPIDER_DIR, "dev_gold.sql"), encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            sql, _, db_id = line.rpartition("\t")
            golds.append((sql.strip(), db_id.strip()))
    assert len(golds) == len(dev), f"gold {len(golds)} != dev {len(dev)}"
    return dev, golds


def run_gold(mysql_db, sql):
    """在 MySQL 执行 gold SQL，成功返回行元组列表，失败抛异常。"""
    my = pymysql.connect(database=mysql_db, **MYSQL)
    try:
        with my.cursor() as c:
            c.execute(f"SET SESSION MAX_EXECUTION_TIME=60000")
            c.execute(sql)
            return c.fetchmany(MAX_ROWS + 1)
    finally:
        my.close()


def norm_cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{round(v, 4):.4f}"
    return str(v).strip()


def norm_rows(rows):
    return sorted(tuple(norm_cell(c) for c in r) for r in rows)


def _norm_r2ci(rows):
    """宽口径归一化：字符串小写去空格、float 3 位小数（吸收 AVG 半进位 0.0001
    级漂移与 gold 落标 4 位舍入的双重舍入差）"""
    out = []
    for r in rows:
        rr = []
        for c in r:
            if c is None:
                rr.append("NULL")
            elif isinstance(c, float):
                rr.append(round(c, 3))
            else:
                rr.append(str(c).strip().lower())
        out.append(tuple(rr))
    return out


def _match_tol(g, s, tol=1.5e-3):
    """容差多重集匹配：字符串单元格为锚点分组，组内浮点排序后配对，
    全部数值格 |a-b|<=tol 记匹配（吸收 AVG 半进位/双重舍入的 0.0001 级漂移；
    tol 取 1.5e-3 覆盖 r3 舍入后 0.001 名义差 + 二进制浮点噪声）"""
    from collections import defaultdict
    gs, ss = defaultdict(list), defaultdict(list)
    for r in g:
        k = tuple(c for c in r if not isinstance(c, float))
        gs[k].append(tuple(c for c in r if isinstance(c, float)))
    for r in s:
        k = tuple(c for c in r if not isinstance(c, float))
        ss[k].append(tuple(c for c in r if isinstance(c, float)))
    if gs.keys() != ss.keys():
        return False
    for k in gs:
        a, b = sorted(gs[k]), sorted(ss[k])
        if len(a) != len(b):
            return False
        for ra, rb in zip(a, b):
            if any(abs(x - y) > tol for x, y in zip(ra, rb)):
                return False
    return True


def wide_compare(gen_rows, gold_rows):
    """宽口径分层比对（对齐 Falcon 收敛版比对器）：r3/ci 精确 -> 数值容差 ->
    列排列 -> 列排列+容差 -> 多余列剔除。返回 (bool, layer)。仅用于 match_wide 统计。"""
    from itertools import permutations
    g = _norm_r2ci(gen_rows)
    s = _norm_r2ci(gold_rows)
    if not g or not s:
        return False, ""
    if sorted(g) == sorted(s):
        return True, "r2ci"
    pc = len(g[0])
    gc = len(s[0])
    if pc == gc and _match_tol(g, s):
        return True, "tol"
    # 列排列（同列数；小列数放宽行数上限：2/3 列排列代价低）
    if pc == gc and 2 <= pc <= 8 and (len(g) <= 200 or (pc <= 3 and len(g) <= 2000)):
        for perm in permutations(range(pc)):
            if sorted(tuple(r[i] for i in perm) for r in g) == sorted(s):
                return True, "perm"
        if pc <= 3:  # 排列+容差（2/3 列代价低）
            for perm in permutations(range(pc)):
                if _match_tol([tuple(r[i] for i in perm) for r in g], s):
                    return True, "perm_tol"
    # 多余列剔除（gen 列数 = gold+1）
    if pc == gc + 1 and gc <= 7 and len(g) <= 200:
        for drop in range(pc):
            if sorted(tuple(c for i, c in enumerate(r) if i != drop) for r in g) == sorted(s):
                return True, "extra_col"
    return False, ""


def _jsonable(v):
    """gold 结果落标 JSON 安全化（MySQL AVG 返回 Decimal，SQLite 值可能为 bytes）"""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v) if isinstance(v, memoryview) else v
        return b.decode("utf-8", "ignore")
    return v


def _is_join(sql):
    import re as _re
    return bool(_re.search(r"\bJOIN\b", sql, _re.I)) or \
        bool(_re.search(r"FROM\s+[`\"\[]?\w+[`\"\]]?\s*,", sql, _re.I))


def cmd_select(n=10, existing_file=None, out_file=None):
    """抽题：默认全新抽 n 题（旧规则）；传 existing_file 时为追加模式——
    在既有选题基础上 round-robin 覆盖所有库继续抽 n 题，输出 out_file。"""
    dev, golds = load_dev()
    by_db = {}
    for i, q in enumerate(dev):
        by_db.setdefault(q["db_id"], []).append((i, q, golds[i][0]))
    db_order = list(by_db.keys())
    print(f"dev 共 {len(dev)} 题 / {len(db_order)} 库", flush=True)

    # 每库候选排序：JOIN 题在前（题序），其后非 JOIN（题序）；第 r 条可执行题即取 ordered 第 r 个
    ordered = {db: ([c for c in by_db[db] if _is_join(c[2])] +
                    [c for c in by_db[db] if not _is_join(c[2])])
               for db in db_order}

    selected, per_db_taken, used = [], {}, set()
    if existing_file:
        with open(existing_file, encoding="utf-8") as f:
            selected = json.load(f)
        used = {q["dev_index"] for q in selected}
        for q in selected:
            per_db_taken[q["db_id"]] = per_db_taken.get(q["db_id"], 0) + 1
        print(f"追加模式：已有 {len(selected)} 题，再选 {n} 题", flush=True)

    imported = {}
    exec_cache = {db: [] for db in db_order}  # db -> [(i, q, gold, rows)] 已验证可执行
    scan_pos = {db: 0 for db in db_order}

    def pick_rth(db_id, r, mysql_db):
        cache = exec_cache[db_id]
        while len(cache) < r and scan_pos[db_id] < len(ordered[db_id]):
            i, q, gold = ordered[db_id][scan_pos[db_id]]
            scan_pos[db_id] += 1
            try:
                rows = run_gold(mysql_db, gold)
            except Exception as e:
                print(f"  [{db_id}] q{i} gold MySQL 不兼容: {str(e)[:100]}", flush=True)
                continue
            cache.append((i, q, gold, rows))
        return cache[r - 1] if len(cache) >= r else None

    total_target = len(selected) + n
    progress = True
    while len(selected) < total_target and progress:
        progress = False
        for db_id in db_order:
            if len(selected) >= total_target:
                break
            mysql_db = f"spider_{db_id}"
            if db_id not in imported:
                import_db(db_id, mysql_db)
                imported[db_id] = mysql_db
            r = per_db_taken.get(db_id, 0) + 1
            item = pick_rth(db_id, r, mysql_db)
            if not item:
                continue  # 该库可执行题已用尽，本轮其余库继续
            i, q, gold, rows = item
            per_db_taken[db_id] = r
            if i in used:
                progress = True  # 理论不发生（确定性顺序），防御
                continue
            used.add(i)
            selected.append({
                "question_id": f"spider_dev_{i}", "dev_index": i, "db_id": db_id,
                "mysql_db": mysql_db, "question": q["question"],
                "gold_sql": gold,
                "gold_result": [[_jsonable(c) for c in x] for x in rows[:MAX_ROWS]],
                "gold_rows_over_limit": len(rows) > MAX_ROWS,
            })
            progress = True
            print(f"[{db_id}] 选 q{i} (该库第{r}题): {q['question']}", flush=True)

    os.makedirs(QUESTIONS_DIR, exist_ok=True)
    out = out_file or os.path.join(QUESTIONS_DIR, "spider_selected.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=1)
    print(f"\n共 {len(selected)} 题（本轮新增 {n}）-> {out}", flush=True)


# ---------------------------------------------------------------- QF API

def api(method, path, **kw):
    last = None
    for attempt in range(6):
        try:
            r = _session().request(method, BASE_URL + path, timeout=TIMEOUT, **kw)
            if r.status_code == 401:
                login()
                continue
            if r.status_code == 429:  # QF 限流：退避重试
                print(f"{method} {path} 429, retry #{attempt+1} after 20s", flush=True)
                time.sleep(20)
                continue
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError as e:
            last = e
            print(f"{method} {path} conn error, retry #{attempt+1} after 30s", flush=True)
            time.sleep(30)
    raise last


def unwrap(resp, key=None):
    if not isinstance(resp, dict):
        return resp
    for k in ([key] if key else ["item", "items", "data"]):
        if k in resp and resp[k] is not None:
            return resp[k]
    if "code" not in resp and "id" in resp:
        return resp
    return None


def login():
    s = _session()
    r = None
    for attempt in range(12):
        try:
            r = s.post(f"{BASE_URL}/login", json={"username": USER, "password": PWD},
                       timeout=30)
        except requests.RequestException:  # 含 ReadTimeout（服务 reload 窗口）
            time.sleep(20)
            continue
        if r.status_code == 429:
            time.sleep(35)
            continue
        r.raise_for_status()
        break
    assert s.cookies.get("token"), f"登录失败: {r.text[:200] if r is not None else 'no resp'}"


def cmd_setup(questions_file):
    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)
    login()
    dbs = sorted({q["mysql_db"] for q in questions})
    for mysql_db in dbs:
        db_id = mysql_db.replace("spider_", "")
        dss = unwrap(api("GET", "/api/sync/datasources")) or []
        ds = next((d for d in dss if d.get("database") == mysql_db), None)
        if not ds:
            ds = unwrap(api("POST", "/api/sync/datasources", json={
                "name": f"Spider-{db_id}", "db_type": "mysql", "host": "127.0.0.1",
                "port": 3306, "database": mysql_db, "username": "root",
                "password": os.environ.get("QF_MYSQL_PASSWORD", "")}))
        ds_id = ds["id"]
        print(f"[{db_id}] datasource id={ds_id}", flush=True)
        print("  test:", api("POST", f"/api/sync/datasources/{ds_id}/test"), flush=True)
        jobs = unwrap(api("GET", "/api/sync/jobs")) or []
        job = next((j for j in jobs if j.get("datasource_id") == ds_id), None)
        if not job:
            try:
                job = unwrap(api("POST", "/api/sync/jobs", json={
                    "datasource_id": ds_id, "sync_mode": "full"}))
            except requests.HTTPError:
                jobs = unwrap(api("GET", "/api/sync/jobs")) or []
                job = next((j for j in jobs if j.get("datasource_id") == ds_id), None)
        job_id = job["id"]
        print(f"[{db_id}] job id={job_id}, run:", api("POST", f"/api/sync/jobs/{job_id}/run"),
              flush=True)
        for i in range(120):
            time.sleep(5)
            items = unwrap(api("GET", f"/api/sync/runs?job_id={job_id}&limit=1")) or []
            if items and items[0].get("status") in ("success", "failed", "error"):
                print(f"[{db_id}] sync {items[0].get('status')}", flush=True)
                break
            if i % 6 == 5:
                print(f"[{db_id}] waiting sync... {i*5}s", flush=True)
    print("build-vector-index:", api("POST", "/api/schema/build-vector-index",
                                     json={"schema_name": None, "rebuild": True}), flush=True)


def _eval_one(q, llm_config_id):
    """单题评测（供多线程调用）。返回不含 gold_result 的记录 dict。"""
    import threading
    t0 = time.time()
    rec = dict(q)
    rec.pop("gold_result", None)
    rec["llm_config_id"] = llm_config_id
    try:
        resp = api("POST", "/api/conversation", json={
            "query": q["question"], "schema_name": q["mysql_db"],
            "db_type": "mysql", "llm_config_id": llm_config_id})
        msg = resp.get("message") or {}
        rec["conversation_id"] = (resp.get("conversation") or {}).get("id")
        rec["gen_sql"] = msg.get("sql")
        rec["is_valid"] = msg.get("is_valid")
        rec["need_more_info"] = msg.get("need_more_info")
        rec["missing_info"] = msg.get("missing_info")
        qr = msg.get("query_result") or {}
        rec["exec_error"] = qr.get("error")
        rec["llm_info"] = msg.get("llm_info")
        rows = qr.get("rows") or []
        gen_norm = norm_rows(rows)
        gold_norm = norm_rows(q["gold_result"])
        rec["gen_rows_count"] = len(gen_norm)
        rec["gold_rows_count"] = len(gold_norm)
        rec["match"] = (gen_norm == gold_norm) and not rec.get("need_more_info")
        if not rec["match"] and rows and not rec.get("need_more_info"):
            ok_w, layer = wide_compare(rows, q["gold_result"])
            rec["match_wide"] = ok_w
            rec["wide_layer"] = layer
    except Exception as e:
        rec["error"] = str(e)[:500]
        rec["match"] = False
    rec["elapsed_s"] = round(time.time() - t0, 1)
    return rec


def cmd_test(questions_file, out_file, llm_config_id=7, workers=1, fallback_ids=None):
    """多线程批量评测。workers>1 时并发调 QF API；fallback_ids 为逗号分隔的
    模型池，多线程模式下按模型分片（一个模型一个线程，round-robin 均分题目），
    单题失败（超时/5xx/限流/配额）时从分片模型起按链轮换重试。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)
    login()
    try:
        with open(out_file, encoding="utf-8") as f:
            results = json.load(f)
    except FileNotFoundError:
        results = []
    done = {r["question_id"] for r in results if not r.get("error")}
    todo = [q for q in questions if q["question_id"] not in done]
    chain = [llm_config_id] + [int(x) for x in (fallback_ids or "").split(",") if x.strip()]
    print(f"待测 {len(todo)}/{len(questions)} 题，workers={workers}，"
          f"配置链={chain}", flush=True)
    lock = threading.Lock()

    def save(rec):
        with lock:
            results.append(rec)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
        print(f"[{rec['question_id']} cfg={rec.get('llm_config_id')}] "
              f"match={rec.get('match')} wide={rec.get('match_wide')} "
              f"err={str(rec.get('error'))[:60]} elapsed={rec['elapsed_s']}s", flush=True)

    def run_question(q, start=None):
        order = ([start] + [c for c in chain if c != start]) if start else chain
        rec = None
        for cfg in order:
            rec = _eval_one(q, cfg)
            if not rec.get("error"):
                break
            print(f"[{q['question_id']}] cfg={cfg} 失败: {str(rec.get('error'))[:120]}，"
                  f"尝试下一个配置", flush=True)
        return rec

    if workers <= 1:
        for q in todo:
            save(run_question(q))
    else:
        # 一个模型一个线程：按配置链把题 round-robin 分片，每个模型独占线程池
        # （workers//模型数 个线程，默认恰好 1）；单题失败仍从分片模型起按链轮换重试
        n_models = len(chain)
        per = max(1, workers // n_models)
        pools = {m: ThreadPoolExecutor(max_workers=per) for m in chain}
        futs = {}
        for idx, q in enumerate(todo):
            futs[pools[chain[idx % n_models]].submit(run_question, q,
                                                     chain[idx % n_models])] = q
        for fut in as_completed(futs):
            save(fut.result())
        for p in pools.values():
            p.shutdown()
    n_ok = sum(1 for r in results if r.get("match"))
    n_okw = sum(1 for r in results if r.get("match_wide"))
    print(f"\n总计(严格): {n_ok}/{len(results)}  (宽口径): {n_okw + n_ok}/{len(results)}",
          flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "import":
        for db_id in sys.argv[2:]:
            import_db(db_id)
    elif cmd == "select":
        cmd_select(int(sys.argv[2]) if len(sys.argv) > 2 else 10,
                   sys.argv[3] if len(sys.argv) > 3 else None,
                   sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "setup":
        cmd_setup(sys.argv[2])
    elif cmd == "test":
        # test <questions> <out> [llm_id] [workers] [fallback_ids]
        cmd_test(sys.argv[2], sys.argv[3],
                 int(sys.argv[4]) if len(sys.argv) > 4 else 7,
                 int(sys.argv[5]) if len(sys.argv) > 5 else 1,
                 sys.argv[6] if len(sys.argv) > 6 else None)
    else:
        print(__doc__)
