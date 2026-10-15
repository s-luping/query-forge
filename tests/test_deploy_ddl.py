# -*- coding: UTF-8 -*-
"""集中式建表 SQL 回归 — 开发纲领 §2 缺口8

锁定两条性质：
    1. deploy/*.sql 与 ORM 元数据同源（无漂移，与 ci_guard 检查项 6 互为双保险）；
    2. DDL 可在全新空库上直接执行，且建出的库对象与 create_all 完全一致。
"""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


@pytest.fixture(scope='module')
def generated():
    import gen_schema_sql
    return gen_schema_sql.generate()


def _all_models():
    for mod in ('user', 'role', 'schema', 'knowledge', 'conversation', 'llm',
                'system', 'vector_index', 'security', 'sync', 'datasource'):
        importlib.import_module(f'models.{mod}')


def test_deploy_sql_in_sync_with_orm(generated):
    """deploy/*.sql 必须与 ORM 元数据一致（防漂移）"""
    for name, content in generated.items():
        path = ROOT / 'deploy' / name
        assert path.exists(), f'{name} 缺失，请运行 python scripts/gen_schema_sql.py'
        on_disk = path.read_text(encoding='utf-8')
        assert on_disk.rstrip('\n') + '\n' == content.rstrip('\n') + '\n', (
            f'{name} 与 ORM 不同步，请重新生成')


def test_ddl_executes_on_fresh_db(generated, tmp_path):
    """DDL 必须能在空库上执行，且与 create_all 产出逐对象一致"""
    from sqlalchemy import create_engine

    _all_models()
    from models.base import LogsBase, MainBase, TelemetryBase

    def schema_objects(db_file):
        conn = sqlite3.connect(db_file)
        try:
            return sorted(
                ''.join(r[0].split())
                for r in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
        finally:
            conn.close()

    for sql_name, base, orm_file in (
            ('schema_main.sql', MainBase, 'orm_main.db'),
            ('schema_telemetry.sql', TelemetryBase, 'orm_tele.db'),
            ('schema_logs.sql', LogsBase, 'orm_logs.db')):
        # 1. DDL 空库执行
        ddl_db = tmp_path / (sql_name.replace('.sql', '.db'))
        conn = sqlite3.connect(ddl_db)
        conn.executescript(generated[sql_name])
        conn.close()
        ddl_objs = schema_objects(ddl_db)
        assert len(ddl_objs) > 0, f'{sql_name} 未建出任何库对象'

        # 2. ORM create_all 同库比对
        orm_db = tmp_path / orm_file
        base.metadata.create_all(create_engine(f'sqlite:///{orm_db}'))
        assert schema_objects(orm_db) == ddl_objs, (
            f'{sql_name} 与 create_all 产出不一致')
