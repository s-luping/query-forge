# -*- coding: UTF-8 -*-
"""由 ORM 元数据生成集中式建表 SQL — 开发纲领 §2 缺口8

用法：
    python scripts/gen_schema_sql.py            # 生成/刷新 deploy/*.sql
    python scripts/gen_schema_sql.py --check    # 仅校验是否漂移（CI 用，退出码非0=漂移）

产出：
    deploy/schema_main.sql       主库（MainBase）建表 DDL
    deploy/schema_telemetry.sql  遥测库（TelemetryBase）建表 DDL
    deploy/schema_logs.sql       日志库（LogsBase）建表 DDL

设计约束：
    - DDL 必须与 models/ 的 ORM 定义同源，禁止手写后不同步；
    - CI 守卫（scripts/ci_guard.py）以 --check 模式校验漂移；
    - SQLite 方言为基准（当前运行时默认），外部数据库由 create_all 建全量表。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEPLOY_DIR = ROOT / 'deploy'


def _render(metadata, title: str) -> str:
    """把 metadata 渲染为带注释头的 DDL 文本（SQLite 方言）"""
    from sqlalchemy.dialects import sqlite as sqlite_dialect
    from sqlalchemy.schema import CreateIndex, CreateTable

    dialect = sqlite_dialect.dialect()
    lines = [
        '-- -*- coding: UTF-8 -*-',
        f'-- {title}',
        '-- 本文件由 scripts/gen_schema_sql.py 自动生成，请勿手改；',
        '-- 修改表结构请改 models/ 下的 ORM 定义后重新生成。',
        '',
    ]
    tables = sorted(metadata.tables.values(), key=lambda t: t.name)
    for table in tables:
        lines.append(f'-- ── {table.name} ──')
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        lines.append(ddl + ';')
        # 索引（含唯一约束隐式索引之外的显式 Index 对象）
        for idx in sorted(table.indexes, key=lambda i: i.name):
            lines.append(str(CreateIndex(idx).compile(dialect=dialect)).strip() + ';')
        lines.append('')
    return '\n'.join(lines)


def generate() -> dict:
    """生成 DDL 文本，返回 {文件名: 内容}"""
    # 显式导入全部模型模块（models/__init__ 只导出少量符号，
    # 必须逐个 import 才能把各表注册进 Base.metadata）
    import importlib
    for mod in ('user', 'role', 'schema', 'knowledge', 'conversation', 'llm',
                'system', 'vector_index', 'security', 'sync', 'datasource'):
        importlib.import_module(f'models.{mod}')
    from models.base import LogsBase, MainBase, TelemetryBase

    return {
        'schema_main.sql': _render(
            MainBase.metadata, '主库建表 DDL（queryforge.db，MainBase）'),
        'schema_telemetry.sql': _render(
            TelemetryBase.metadata, '遥测库建表 DDL（llm_telemetry.db，TelemetryBase）'),
        'schema_logs.sql': _render(
            LogsBase.metadata, '日志库建表 DDL（logs.db，LogsBase）'),
    }


def main() -> int:
    check_mode = '--check' in sys.argv
    DEPLOY_DIR.mkdir(exist_ok=True)

    drifted = []
    for name, content in generate().items():
        path = DEPLOY_DIR / name
        new = content.rstrip('\n') + '\n'
        old = path.read_text(encoding='utf-8') if path.exists() else ''
        if check_mode:
            if new != old:
                drifted.append(name)
                print(f'[DRIFT] {name} 与 ORM 定义不同步，请运行 python scripts/gen_schema_sql.py')
        else:
            path.write_text(new, encoding='utf-8')
            print(f'[OK] 已生成 {path.relative_to(ROOT)}')

    if check_mode:
        if drifted:
            return 1
        print('[OK] deploy/*.sql 与 ORM 定义同步')
    return 0


if __name__ == '__main__':
    sys.exit(main())
