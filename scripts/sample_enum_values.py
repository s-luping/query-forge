# -*- coding: UTF-8 -*-
"""实采枚举值采样 — 知识库 value_domain 条目的事实来源

背景（docs/测试报告/Falcon知识库优化对比_20261017.html 结论）：
    知识库枚举条目若写常识推测值（"钻石" vs "Diamond"），模型会照着猜；
    必须写**源库实采原样值**（含大小写、尾随空格），并要求逐字符照抄。
    本脚本把"实采"变成可重复的运维动作：连已登记数据源，只读 SELECT DISTINCT。

用法：
    # 单表单列（--schema 传库名 db_schemas.name，经其数据源连接）
    .venv\\Scripts\\python.exe scripts\\sample_enum_values.py --schema DM ^
        --table DM_KEY_BUDGET_INDICATOR_DATA_METRIC --columns SCENARIO,VERSION

    # 多张表同一批列（每张表分别输出）
    .venv\\Scripts\\python.exe scripts\\sample_enum_values.py --schema DM ^
        --table DM_KEY_ACTUAL_INDICATOR_DATA_METRIC DM_KEY_BUDGET_INDICATOR_DATA_METRIC ^
        --columns PERIODS,QUARTERS --limit 60

    # 顺带看维度编码规模（不写值，只计数），判断是否需要枚举条目
    .venv\\Scripts\\python.exe scripts\\sample_enum_values.py --datasource fr-dm ^
        --table DM_KEY_ACTUAL_INDICATOR_DATA_METRIC --columns ACCOUNT,ENTITY,PROJECT_LINE --count-only

安全约束：
    - 仅允许 SELECT（复用 services.sql_executor._validate_select_only 断言）
    - 连接参数走数据源登记配置（密码 Fernet 解密），不落地任何凭据
    - LIMIT 上限硬编码，禁止全量拉取
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import URL, create_engine  # noqa: E402

from app.crypto import decrypt_secret  # noqa: E402
from services.sql_executor import _resolve_datasource, _validate_select_only  # noqa: E402

MAX_LIMIT = 500  # 硬上限：单列最多采样 500 个不同值
CONNECT_TIMEOUT = 5  # 秒：连不上快速失败，不挂死运维终端
READ_TIMEOUT = 30  # 秒：慢库单条采样语句上限


def _build_sampling_engine(ds: dict):
    """自带超时的只读引擎（主链路的执行引擎无 connect_timeout，采样脚本须可挂不了）"""
    db_type = (ds.get('db_type') or '').lower()
    password = decrypt_secret(ds.get('password_enc') or '') if ds.get('password_enc') else ''
    if db_type in ('mysql', 'mariadb', 'doris'):
        return create_engine(URL.create(
            'mysql+pymysql', username=ds.get('username') or '',
            password=password, host=ds.get('host') or 'localhost',
            port=ds.get('port') or 3306, database=ds.get('database') or '',
            query={'charset': 'utf8mb4'},
        ), connect_args={'connect_timeout': CONNECT_TIMEOUT, 'read_timeout': READ_TIMEOUT},
            pool_pre_ping=True, pool_size=1)
    if db_type in ('postgresql', 'postgres'):
        return create_engine(URL.create(
            'postgresql+psycopg2', username=ds.get('username') or '',
            password=password, host=ds.get('host') or 'localhost',
            port=ds.get('port') or 5432, database=ds.get('database') or '',
        ), connect_args={'connect_timeout': CONNECT_TIMEOUT},
            pool_pre_ping=True, pool_size=1)
    raise SystemExit(f"[ERR] 采样脚本暂不支持该数据库类型: {db_type}（MySQL/PG 之外请手工连库导）")


def sample(schema_name: str, tables: list, columns: list, limit: int, count_only: bool) -> int:
    ds = _resolve_datasource(schema_name)
    if not ds:
        print(f"[ERR] 库不存在或未关联数据源: {schema_name}（应传 db_schemas.name，如 DM）")
        return 2
    engine = _build_sampling_engine(ds)
    db_name = ds['database']
    exit_code = 0
    try:
        with engine.connect() as conn:
            for table in tables:
                print(f"\n=== {db_name}.{table} (db_type={ds['db_type']}) ===")
                for col in columns:
                    if count_only:
                        sql = f"SELECT COUNT(DISTINCT `{col}`) FROM `{db_name}`.`{table}`"
                    else:
                        sql = (f"SELECT DISTINCT `{col}` FROM `{db_name}`.`{table}` "
                               f"ORDER BY `{col}` LIMIT {min(limit, MAX_LIMIT)}")
                    _validate_select_only(sql, ds['db_type'])
                    try:
                        rows = [r[0] for r in conn.execute(text(sql))]
                    except Exception as e:
                        print(f"  {col}: [ERR] {e}")
                        exit_code = 1
                        continue
                    if count_only:
                        print(f"  {col}: {rows[0]} 个不同值")
                    else:
                        shown = ', '.join(repr(v) for v in rows[:limit])
                        more = f" …(共{len(rows)}个)" if len(rows) >= limit else ''
                        print(f"  {col}: {shown}{more}")
    finally:
        engine.dispose()
    return exit_code


def main():
    parser = argparse.ArgumentParser(description='只读采样数据源枚举实采值（知识库 value_domain 依据）')
    parser.add_argument('--schema', required=True, help='库名（db_schemas.name，如 DM；经其数据源连接）')
    parser.add_argument('--table', nargs='+', required=True, help='表名（不带库前缀，可多张）')
    parser.add_argument('--columns', required=True, help='逗号分隔的列名')
    parser.add_argument('--limit', type=int, default=50, help='每列最多展示值数（硬上限 500）')
    parser.add_argument('--count-only', action='store_true', help='只统计不同值个数，不列值')
    args = parser.parse_args()
    columns = [c.strip() for c in args.columns.split(',') if c.strip()]
    sys.exit(sample(args.schema, args.table, columns, args.limit, args.count_only))


if __name__ == '__main__':
    main()
