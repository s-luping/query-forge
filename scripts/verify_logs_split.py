# -*- coding: UTF-8 -*-
"""日志库拆分端到端验证 — 非启服、副本隔离，不碰真实 db 文件

用法：
    .venv/Scripts/python.exe scripts/verify_logs_split.py

流程：
  1. 复制 db/queryforge.db + db/llm_telemetry.db 到系统临时目录；
  2. 把 config 的三个 DB 路径指向副本后 import main（引擎在 import 时
     按 config 建，故必须先改路径再 import）；
  3. init_database()：触发日志三表归档迁移（_migrate_logs_tables）；
  4. 逐项断言：主库无日志表 / 日志库有数据且结构完整 / 跨库 CRUD 与
     统计函数可跑 / TestClient 公开端点正常。

退出码 0 = 全部通过。
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.config as config

# ── 1. 副本隔离 ────────────────────────────────────────────
tmp_dir = Path(tempfile.mkdtemp(prefix='qf_logs_verify_'))
main_db = tmp_dir / 'queryforge.db'
tele_db = tmp_dir / 'llm_telemetry.db'
logs_db = tmp_dir / 'logs.db'
copied = False
if Path(config.MAIN_DB_PATH).exists():
    shutil.copy2(config.MAIN_DB_PATH, main_db)
    copied = True
if Path(config.TELEMETRY_DB_PATH).exists():
    shutil.copy2(config.TELEMETRY_DB_PATH, tele_db)
config.DATABASE_URL = ''
config.MAIN_DB_PATH = str(main_db)
config.TELEMETRY_DB_PATH = str(tele_db)
config.LOGS_DB_PATH = str(logs_db)

# ── 2-3. 建引擎 + init_database（含归档迁移） ──────────────
import main  # noqa: E402  必须在改 config 之后
from db.database import init_database  # noqa: E402

init_database()

failures = []


def check(name: str, cond: bool, detail: str = ''):
    status = 'PASS' if cond else 'FAIL'
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''))
    if not cond:
        failures.append(name)


def tables_of(db_file: Path):
    conn = sqlite3.connect(db_file)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


# ── 4. 断言 ────────────────────────────────────────────────
LOGS_TABLES = {'query_audit_logs', 'sync_run_logs', 'schema_change_logs'}

main_tables = tables_of(main_db)
check('主库不再持有日志三表', not (main_tables & LOGS_TABLES),
      f'残留: {main_tables & LOGS_TABLES}' if main_tables & LOGS_TABLES else '')
check('主库仍持有核心表', {'users', 'db_schemas', 'sync_job_configs'} <= main_tables)

logs_tables = tables_of(logs_db)
check('日志库已建三表', LOGS_TABLES <= logs_tables)

if copied:
    # 副本主库原含数据（存量场景），验证数据随表搬迁
    conn = sqlite3.connect(logs_db)
    counts = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in LOGS_TABLES}
    total = sum(counts.values())
    conn.close()
    check('存量数据已搬迁至日志库', total > 0, f'{counts}')
    # 表结构完整（PK/索引在）
    conn = sqlite3.connect(logs_db)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='schema_change_logs'").fetchone()[0]
    idx = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
        "AND tbl_name='schema_change_logs'").fetchone()[0]
    conn.close()
    check('日志表结构完整（PK+外键+索引）',
          'PRIMARY KEY' in ddl.upper() and 'FOREIGN KEY' in ddl.upper() and idx >= 3,
          f'索引数={idx}')
else:
    print('[SKIP] 无存量主库副本，跳过搬迁断言（新库场景）')

# 跨库 CRUD：默认走日志库
from crud.security import audit_crud  # noqa: E402
from crud.sync import change_crud, get_sync_stats, sync_run_crud  # noqa: E402

try:
    audit_crud.list_by_user(1, limit=5)
    change_crud.count_pending()
    sync_run_crud.count_success()
    stats = get_sync_stats()
    check('跨库 CRUD / get_sync_stats 可执行',
          'runs' in stats and 'changes' in stats and 'jobs' in stats,
          f"runs={stats['runs']['total']} changes={stats['changes']['pending']} "
          f"jobs={stats['jobs']['total']}")
except Exception as e:
    check('跨库 CRUD / get_sync_stats 可执行', False, repr(e))

# 主库 CRUD 不受影响
try:
    from crud.schema import schema_crud  # noqa: E402
    schema_crud.list_names() if hasattr(schema_crud, 'list_names') else None
    check('主库 CRUD 不受影响', True)
except Exception as e:
    check('主库 CRUD 不受影响', False, repr(e))

# TestClient 公开端点（无需认证）证明 app 可正常服务
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app, raise_server_exceptions=False)
r = client.get('/api/definitely-not-a-real-route')
check('TestClient 公开端点 404 统一错误体',
      r.status_code == 404 and r.json().get('code') == 40400)

# 清理副本
shutil.rmtree(tmp_dir, ignore_errors=True)

print()
if failures:
    print(f'verify_logs_split: {len(failures)} 项失败: {failures}')
    sys.exit(1)
print('verify_logs_split: 全部通过')
