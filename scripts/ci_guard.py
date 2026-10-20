# -*- coding: UTF-8 -*-
"""CI 反模式守卫 — 《开发纲领》§6.3 的静态检查落地

检查项：
    1. 红线能力回归：collect / scan-doris / sync-doris / collect-stats / meta_collect /
       total_row / total_size_mb 等纲领 §6.2 点名能力禁止出现在代码中
    2. 循环 SHOW：for 循环窗口内出现 SHOW CREATE TABLE / SHOW DATA / 逐表统计
       （人工单表详情接口允许一次 SHOW，需行内标注 `# ci-guard: allow` 并登记总表）
    3. 路由登记：所有 router 的路由必须在 docs/03-资产总表.md 接口清单中登记；
       新增 router 文件必须先在 ROUTER_REGISTRY 登记（纲领 §5.3）
    4. 表登记：models 中所有 __tablename__ 必须在总表「表清单」登记
    5. 作业登记：scheduler/jobs/ 下每个作业必须在总表「调度作业」登记；
       作业类型 meta_collect 禁止出现
    6. DDL 漂移：deploy/*.sql 必须与 ORM 元数据同源（缺口8），
       改 models 后未重新生成建表 SQL 即报错

用法：
    python scripts/ci_guard.py            # 全量检查，发现问题退出码 1
    行内豁免：# ci-guard: allow           # 允许单条 SHOW（人工单表详情场景）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 1. 红线 token（纲领 §6.2 / §6.3）─────────────────────────
FORBIDDEN_TOKENS = [
    r'\bscan-doris\b', r'\bsync-doris\b', r'\bcollect-stats\b',
    r'\bmeta_collect\b', r'\btotal_row\b', r'\btotal_size_mb\b',
    r'/warehouse/collect\b', r'\bcollect-logs\b',
]

# 允许包含红线 token 的文件（纲领文档自身）
TOKEN_ALLOW_FILES = {'开发纲领.md', 'docs\\03-资产总表.md', 'docs/03-资产总表.md',
                     'scripts\\ci_guard.py', 'scripts/ci_guard.py'}

# 扫描范围：业务代码 + 前端
SCAN_GLOBS = ['*.py', 'static/js/*.js']
SCAN_EXCLUDE_PARTS = {'.venv', '__pycache__', 'static/vendor', 'models/embeddings',
                      '.git', 'logs', 'docs'}

# ── 2. 循环 SHOW 检测 ────────────────────────────────────────
SHOW_PATTERNS = [re.compile(r'\bSHOW\s+CREATE\s+TABLE\b', re.I),
                 re.compile(r'\bSHOW\s+DATA\b', re.I),
                 re.compile(r'\bSHOW\s+TABLE\s+STATUS\b', re.I),
                 re.compile(r'\bSELECT\s+COUNT\s*\(\s*\*\s*\).*\bFROM\b.*information_schema', re.I | re.S)]
LOOP_RE = re.compile(r'^\s*for\s+\w+\s+in\b')
ALLOW_RE = re.compile(r'#\s*ci-guard:\s*allow')
LOOP_WINDOW = 8  # for 行之后的检测窗口

# ── 3. 路由登记：router 文件 → [(router 变量名, 挂载前缀)] ──
# 新增 router 文件必须先在此登记，否则守卫报错（纲领 §5.3）
ROUTER_REGISTRY = {
    'app/routers/auth_router.py': [('router', '')],
    'app/routers/page_router.py': [('router', '')],
    'app/routers/user_router.py': [('router', '/api/user')],
    'app/routers/schema_router.py': [('router', '/api/schema')],
    'app/routers/knowledge_router.py': [('router', '/api/knowledge')],
    'app/routers/llm_router.py': [('log_router', '/api/llm'),
                                  ('config_router', '/api/llm-config')],
    'app/routers/conversation_router.py': [('router', '/api/conversation')],
    'app/routers/system_router.py': [('router', '/api/system')],
    'app/routers/permission_router.py': [('router', '/api/permission')],
    'app/routers/security_router.py': [('router', '/api/audit')],
    'app/routers/sync_router.py': [('router', '/api/sync')],
    'app/routers/driver_router.py': [('router', '/api/driver')],
    'app/routers/scheduler_router.py': [('router', '/api/scheduler')],
    'app/routers/docs_router.py': [('router', '')],
}

ROUTE_DECORATOR_RE = re.compile(
    r'@(\w+)\.(get|post|put|delete|patch)\(\s*[\'"]([^\'"]*)[\'"]')
ROUTE_METHODS = {'get': 'GET', 'post': 'POST', 'put': 'PUT', 'delete': 'DELETE', 'patch': 'PATCH'}

# 总表解析
REGISTRY_FILE = ROOT / 'docs' / '03-资产总表.md'
REGISTRY_ROUTE_RE = re.compile(r'\b(GET|POST|PUT|DELETE|PATCH)\s+(/[^\s|`]*)')
SECTION_SPLIT_RE = re.compile(r'^##\s+(.+)$', re.M)
TABLENAME_RE = re.compile(r'`([a-z][a-z0-9_]+)`')
JOBNAME_RE = re.compile(r'`([a-z][a-z0-9_.]+)`')  # 作业含点分模块名

# ── 5. 作业登记 ──────────────────────────────────────────────
JOBS_DIR = ROOT / 'scheduler' / 'jobs'


def _iter_code_files():
    for pattern in SCAN_GLOBS:
        for f in ROOT.glob(pattern):
            rel = f.relative_to(ROOT).as_posix()
            parts = f.relative_to(ROOT).parts
            if SCAN_EXCLUDE_PARTS & set(parts):
                continue
            if rel in ('scripts/ci_guard.py',):
                continue
            yield f, rel


def check_forbidden_tokens(errors):
    """检查 1+5 的 token 部分：红线能力回归"""
    for f, rel in _iter_code_files():
        text = f.read_text(encoding='utf-8', errors='ignore')
        for line_no, line in enumerate(text.splitlines(), 1):
            for token_re in FORBIDDEN_TOKENS:
                if re.search(token_re, line):
                    errors.append(
                        f"[红线回归] {rel}:{line_no} 出现禁用标识 '{token_re}': {line.strip()[:80]}")


def check_loop_show(errors):
    """检查 2：for 循环窗口内的 SHOW / 逐表统计"""
    for f, rel in _iter_code_files():
        if not rel.endswith('.py'):
            continue
        lines = f.read_text(encoding='utf-8', errors='ignore').splitlines()
        for i, line in enumerate(lines):
            if not LOOP_RE.match(line):
                continue
            window = '\n'.join(lines[i:i + LOOP_WINDOW])
            for pat in SHOW_PATTERNS:
                m = pat.search(window)
                if m and not ALLOW_RE.search(window):
                    errors.append(
                        f"[循环SHOW] {rel}:{i + 1} for 循环内疑似逐表执行 "
                        f"'{m.group(0)[:40]}'（人工单表场景请行内标注 # ci-guard: allow 并登记总表）")


def _load_registry():
    """解析总表 → (已登记路由集合, 表名集合, 作业名集合, router文件集合)"""
    routes, tablenames, jobs, router_files = set(), set(), set(), set()
    if not REGISTRY_FILE.exists():
        return routes, tablenames, jobs, router_files, False

    text = REGISTRY_FILE.read_text(encoding='utf-8', errors='ignore')
    sections = {}  # 标题 → 内容
    matches = list(SECTION_SPLIT_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[m.end():end]

    for title, body in sections.items():
        if '接口清单' in title:
            for m in REGISTRY_ROUTE_RE.finditer(body):
                routes.add((m.group(1).upper(), m.group(2).rstrip('/')))
        elif '表清单' in title:
            tablenames |= set(TABLENAME_RE.findall(body))
        elif '调度作业' in title:
            jobs |= set(JOBNAME_RE.findall(body))
        elif '路由文件' in title:
            router_files |= set(re.findall(r'[`]?((?:app/routers|app\\routers)/\w+\.py)[`]?', body))
    return routes, tablenames, jobs, router_files, True


def check_routes(errors, registry_routes):
    """检查 3：代码路由必须登记总表；router 文件必须登记 ROUTER_REGISTRY"""
    code_routes = set()
    for rel, router_defs in ROUTER_REGISTRY.items():
        f = ROOT / rel
        if not f.exists():
            errors.append(f"[路由登记] 总表 REGISTRY 中的 router 文件不存在: {rel}")
            continue
        text = f.read_text(encoding='utf-8', errors='ignore')
        for var, method, path in ROUTE_DECORATOR_RE.findall(text):
            if var not in (v for v, _ in router_defs):
                errors.append(f"[路由登记] {rel} 的 @{var}.{method} 未在 "
                              f"scripts/ci_guard.py ROUTER_REGISTRY 登记该 router 变量")
                continue
            prefix = next(p for v, p in router_defs if v == var)
            full = prefix + path
            code_routes.add((ROUTE_METHODS[method], full.rstrip('/')))

    for f in (ROOT / 'app' / 'routers').glob('*.py'):
        rel = f.relative_to(ROOT).as_posix()
        if rel == 'app/routers/__init__.py':
            continue
        if rel not in ROUTER_REGISTRY:
            errors.append(f"[路由登记] 存在未登记的 router 文件: {rel}（"
                          f"需加入 ROUTER_REGISTRY 并登记 docs/03-资产总表.md）")

    unregistered = code_routes - registry_routes
    for method, path in sorted(unregistered):
        errors.append(f"[路由登记] 接口未登记总表: {method} {path}")


def check_tables(errors, registry_tablenames):
    """检查 4：models 表必须登记总表"""
    model_files = (ROOT / 'models').glob('*.py')
    tn_re = re.compile(r'__tablename__\s*=\s*[\'"](\w+)[\'"]')
    for f in model_files:
        text = f.read_text(encoding='utf-8', errors='ignore')
        for tn in tn_re.findall(text):
            if tn not in registry_tablenames:
                errors.append(f"[表登记] 表未登记总表: {tn}（{f.name}）")


def check_jobs(errors, registry_jobs):
    """检查 5：scheduler/jobs 作业必须登记总表"""
    for f in JOBS_DIR.glob('*.py'):
        if f.name == '__init__.py':
            continue
        module = f'scheduler.jobs.{f.stem}'
        if module not in registry_jobs and f.stem not in registry_jobs:
            errors.append(f"[作业登记] 调度作业未登记总表: {module}")


def check_ddl_drift(errors):
    """检查 6：deploy/*.sql 与 ORM 元数据漂移（缺口8）

    复用 scripts/gen_schema_sql.py 的生成逻辑做内存比对，
    不写文件；models 变更后未重新生成即报错。
    """
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        import gen_schema_sql
    except Exception as e:  # 生成器自身不可用属于构建问题，直接报错
        errors.append(f"[DDL漂移] 无法加载 scripts/gen_schema_sql.py: {e}")
        return
    for name, content in gen_schema_sql.generate().items():
        path = ROOT / 'deploy' / name
        if not path.exists():
            errors.append(
                f"[DDL漂移] {name} 缺失，请运行 python scripts/gen_schema_sql.py")
            continue
        old = path.read_text(encoding='utf-8')
        if old.rstrip('\n') + '\n' != content.rstrip('\n') + '\n':
            errors.append(
                f"[DDL漂移] {name} 与 ORM 定义不同步，"
                f"请运行 python scripts/gen_schema_sql.py 重新生成")


def main() -> int:
    errors = []

    check_forbidden_tokens(errors)
    check_loop_show(errors)

    routes, tablenames, jobs, _router_files, ok = _load_registry()
    if not ok:
        errors.append(f"[资产总表] 未找到 {REGISTRY_FILE}，无法做登记核对（纲领 §5）")
    else:
        check_routes(errors, routes)
        check_tables(errors, tablenames)
        check_jobs(errors, jobs)

    check_ddl_drift(errors)

    if errors:
        print(f'ci_guard: {len(errors)} 个问题')
        for e in errors:
            print(f'  {e}')
        return 1
    print('ci_guard: 全部通过（红线 / 循环SHOW / 路由 / 表 / 作业登记 / DDL漂移）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
