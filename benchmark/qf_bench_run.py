# -*- coding: utf-8 -*-
"""QueryForge × BIRD 基准测试驱动。

用法:
  python qf_bench_run.py setup     # 建数据源 -> 测试连接 -> 建同步任务 -> 执行 -> 重建向量索引
  python qf_bench_run.py test      # 对 questions/bird_selected_questions.json 逐题调 QF NL2SQL 并对比标准答案
"""
import json
import os
import sys
import time

import requests

BASE = "http://localhost:8888"
USER, PWD = "admin", "REDACTED"
LLM_CONFIG_ID = 5  # doubao-seed-2-1-turbo-260628（id=4 pro 配额已耗尽被暂停）
DBS = [("bird_superhero", "superhero"), ("bird_formula_1", "formula_1"),
       ("bird_financial", "financial")]
SEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions", "bird_selected_questions.json")
OUT = r"D:\projects\query-forge\benchmark\results\bird_eval_turbo.json"
TOKEN = None
SESSION = requests.Session()  # token 经 HttpOnly cookie 下发，用 session 自动携带
TIMEOUT = 600


def api(method, path, **kw):
    last = None
    for attempt in range(6):
        try:
            r = SESSION.request(method, BASE + path, timeout=TIMEOUT, **kw)
            if r.status_code == 401:  # 服务重启后 JWT 失效 -> 重新登录
                print(f"{method} {path} got 401, re-login", flush=True)
                login()
                continue
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError as e:  # 服务 reload/重启窗口
            last = e
            print(f"{method} {path} conn error, retry #{attempt+1} after 30s", flush=True)
            time.sleep(30)
    raise last


def unwrap(resp, key=None):
    """QF 统一响应 {code, success, message, item/items/data}；部分接口直接返回模型对象"""
    if not isinstance(resp, dict):
        return resp
    for k in ([key] if key else ["item", "items", "data"]):
        if k in resp and resp[k] is not None:
            return resp[k]
    if "code" not in resp and "id" in resp:
        return resp  # 平铺的模型对象
    return None


def login():
    for attempt in range(12):
        try:
            r = SESSION.post(f"{BASE}/login", json={"username": USER, "password": PWD},
                             timeout=30)
        except requests.ConnectionError:
            print(f"login conn refused, retry #{attempt+1} after 20s", flush=True)
            time.sleep(20)
            continue
        if r.status_code == 429:  # 登录限流 2/minute
            print(f"login 429, retry #{attempt+1} after 35s", flush=True)
            time.sleep(35)
            continue
        r.raise_for_status()
        break
    assert SESSION.cookies.get("token"), f"登录后未获得 cookie: {r.json()}"


def setup():
    login()
    for mysql_db, db_id in DBS:
        # 已存在同名数据源则复用
        dss = unwrap(api("GET", "/api/sync/datasources")) or []
        ds = next((d for d in dss if d.get("database") == mysql_db), None)
        if not ds:
            ds = unwrap(api("POST", "/api/sync/datasources", json={
                "name": f"BIRD-{db_id}", "db_type": "mysql", "host": "127.0.0.1",
                "port": 3306, "database": mysql_db, "username": "root",
                "password": "REDACTED"}))
        ds_id = ds["id"]
        print(f"[{db_id}] datasource id={ds_id}")
        print("  test:", api("POST", f"/api/sync/datasources/{ds_id}/test"))
        # 已有任务复用，否则新建
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
        print(f"[{db_id}] job id={job_id}, run:", api("POST", f"/api/sync/jobs/{job_id}/run"))
        # 轮询 runs 直到该 job 最新一次完成
        for i in range(120):
            time.sleep(5)
            items = unwrap(api("GET", f"/api/sync/runs?job_id={job_id}&limit=1")) or []
            if items:
                st = items[0].get("status")
                if st in ("success", "failed", "error"):
                    print(f"[{db_id}] sync {st}: tables {items[0].get('tables_synced')}/{items[0].get('tables_total')}")
                    break
            if i % 6 == 5:
                print(f"[{db_id}] waiting sync... {i*5}s")
        else:
            print(f"[{db_id}] sync 超时未完成")
    # 全量重建向量索引
    print("build-vector-index:", api("POST", "/api/schema/build-vector-index",
                                     json={"schema_name": None, "rebuild": True}))


def norm_cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{round(v, 4):.4f}"
    return str(v).strip()


def run_test():
    login()
    with open(SEL, encoding="utf-8") as f:
        questions = json.load(f)
    # 断点续跑：已完成(question_id 已记录)的跳过
    try:
        with open(OUT, encoding="utf-8") as f:
            results = json.load(f)
    except FileNotFoundError:
        results = []
    done = {r["question_id"] for r in results if not r.get("error")}  # 异常题重试
    for i, q in enumerate(questions):
        if q["question_id"] in done:
            continue
        print(f"\n=== [{i+1}/{len(questions)}] {q['db_id']} {q['difficulty']} "
              f"qid={q['question_id']} ===", flush=True)
        print("Q:", q["question"], flush=True)
        t0 = time.time()
        rec = dict(q)
        try:
            resp = api("POST", "/api/conversation", json={
                "query": q["question"], "schema_name": q["mysql_db"],
                "db_type": "mysql", "llm_config_id": LLM_CONFIG_ID})
            msg = resp.get("message") or {}
            rec["conversation_id"] = (resp.get("conversation") or {}).get("id")
            rec["gen_sql"] = msg.get("sql")
            rec["is_valid"] = msg.get("is_valid")
            rec["need_more_info"] = msg.get("need_more_info")
            rec["missing_info"] = msg.get("missing_info")
            qr = msg.get("query_result") or {}
            rec["exec_error"] = qr.get("error")
            rows = qr.get("rows") or []
            gen_norm = sorted(tuple(norm_cell(c) for c in r) for r in rows)
            gold_norm = sorted(tuple(norm_cell(c) for c in r) for r in q["gold_result"])
            rec["gen_rows_count"] = len(gen_norm)
            rec["match"] = (gen_norm == gold_norm)
        except Exception as e:
            rec["error"] = str(e)[:500]
            rec["match"] = False
        rec["elapsed_s"] = round(time.time() - t0, 1)
        results.append(rec)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        ok = rec["match"]
        print(f"-> match={ok} elapsed={rec['elapsed_s']}s "
              f"gen_sql={str(rec.get('gen_sql'))[:120]}", flush=True)
    n_ok = sum(1 for r in results if r["match"])
    print(f"\n总计: {n_ok}/{len(results)}")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        LLM_CONFIG_ID = int(sys.argv[2])
    if len(sys.argv) > 3:
        OUT = sys.argv[3]
    {"setup": setup, "test": run_test}[sys.argv[1]]()
