# -*- coding: utf-8 -*-
"""Falcon 基准库一键接入 QueryForge（对应 docs/08-NL2SQL基准测试方案.md 第 3 节）。

动作：登录 → 为每个 falcon_dev_<db_id> 创建数据源 → 连通性测试 →
创建同步任务 → 触发同步并轮询完成 → 最后重建全量向量索引。

幂等：数据源按名称去重复用；任务按数据源名查找复用。

用法（项目 venv，cwd=项目根）：
    .venv\\Scripts\\python.exe benchmark\\setup_sync.py
"""
import json
import os
import sys
import time

import requests

BASE_URL = os.environ.get("QF_BASE_URL", "http://localhost:8888")
USERNAME = os.environ.get("QF_USER", "admin")
PASSWORD = os.environ.get("QF_PASSWORD", "REDACTED")
MYSQL_CONF = dict(
    host=os.environ.get("QF_MYSQL_HOST", "127.0.0.1"),
    port=int(os.environ.get("QF_MYSQL_PORT", "3306")),
    user=os.environ.get("QF_MYSQL_USER", "root"),
    password=os.environ.get("QF_MYSQL_PASSWORD", "REDACTED"),
    charset="utf8mb4",
    autocommit=True,
)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def falcon_schemas():
    dev_path = os.path.join(os.path.dirname(__file__), "questions", "questions_falcon.jsonl")
    schemas = set()
    with open(dev_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                schemas.add(json.loads(line)["schema"])
    return sorted(schemas)


def main():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/login",
               json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    log("登录成功")

    schemas = falcon_schemas()
    log(f"待接入 {len(schemas)} 个基准库: {schemas}")

    # 现有数据源
    r = s.get(f"{BASE_URL}/api/sync/datasources", timeout=30)
    r.raise_for_status()
    ds_items = r.json()
    ds_items = ds_items.get("items", []) if isinstance(ds_items, dict) else ds_items
    existing = {d["name"]: d["id"] for d in ds_items}

    # 现有任务
    r = s.get(f"{BASE_URL}/api/sync/jobs", timeout=30)
    r.raise_for_status()
    job_items = r.json()
    job_items = job_items.get("items", []) if isinstance(job_items, dict) else job_items
    jobs_by_ds = {j["datasource_id"]: j["id"] for j in job_items}

    for schema in schemas:
        ds_id = existing.get(schema)
        if not ds_id:
            r = s.post(f"{BASE_URL}/api/sync/datasources", json={
                "name": schema, "db_type": "mysql",
                "host": MYSQL_CONF["host"], "port": MYSQL_CONF["port"],
                "database": schema, "username": MYSQL_CONF["user"],
                "password": MYSQL_CONF["password"],
            }, timeout=30)
            r.raise_for_status()
            ds_id = r.json()["id"]
            log(f"创建数据源 {schema} id={ds_id}")
        else:
            log(f"复用数据源 {schema} id={ds_id}")

        r = s.post(f"{BASE_URL}/api/sync/datasources/{ds_id}/test", timeout=60)
        ok = r.ok and (r.json() or {}).get("success", True)
        log(f"  连通性测试: {'OK' if ok else r.text[:200]}")
        if not ok:
            sys.exit(f"数据源 {schema} 连接失败")

        job_id = jobs_by_ds.get(ds_id)
        if not job_id:
            r = s.post(f"{BASE_URL}/api/sync/jobs", json={
                "datasource_id": ds_id, "sync_mode": "full",
                "schedule_type": "manual", "auto_classify": True,
            }, timeout=30)
            if r.status_code == 422:  # schedule_type 枚举可能不接受 manual
                r = s.post(f"{BASE_URL}/api/sync/jobs", json={
                    "datasource_id": ds_id, "sync_mode": "full",
                    "schedule_type": "interval", "schedule_value": "9999",
                    "auto_classify": True,
                }, timeout=30)
            r.raise_for_status()
            job = r.json()
            job_id = job["id"]
            log(f"创建同步任务 id={job_id}")
        else:
            log(f"复用同步任务 id={job_id}")

        r = s.post(f"{BASE_URL}/api/sync/jobs/{job_id}/run", timeout=60)
        r.raise_for_status()
        log(f"触发同步 run: {r.json()}")

        # 轮询该数据源最新 run 直至结束
        deadline = time.time() + 900
        while time.time() < deadline:
            time.sleep(5)
            r = s.get(f"{BASE_URL}/api/sync/runs", params={"job_id": job_id},
                      timeout=30)
            runs = r.json() if r.ok else []
            runs = runs.get("items", []) if isinstance(runs, dict) else runs
            mine = [x for x in runs if x.get("job_id") == job_id]
            if mine:
                latest = sorted(mine, key=lambda x: x.get("id", 0))[-1]
                if latest.get("status") in ("success", "failed"):
                    log(f"  同步结束: {latest.get('status')} "
                        f"tables={latest.get('tables_synced')} err={latest.get('error_message')}")
                    if latest.get("status") == "failed":
                        sys.exit(f"同步失败: {latest}")
                    break
        else:
            sys.exit(f"同步超时未完成: {schema}")

    # 重建全量向量索引（必须带 body）
    log("重建全量向量索引…")
    r = s.post(f"{BASE_URL}/api/schema/build-vector-index",
               json={"schema_name": None, "rebuild": True}, timeout=600)
    log(f"build-vector-index: {r.status_code} {r.text[:300]}")
    print("全部接入完成")


if __name__ == "__main__":
    main()
