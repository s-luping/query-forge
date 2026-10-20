# -*- coding: UTF-8 -*-
"""P3 模块依赖红线（静态 AST 检查）— docs/07-ChatSQL模块化与全链路留痕设计.md §6.3

不引入新依赖：ast.parse 逐文件收集 import，断言禁止的依赖边不存在。
新增红线时在 FORBIDDEN_EDGES 加一行即可；业务模块 → app.routers 为全局规则。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 模块 → 禁止 import 的顶层包/模块前缀（按 import 语句的 module 名前缀匹配）
FORBIDDEN_EDGES = {
    'core/gen_sql.py': ['services', 'app.permissions', 'app.routers'],
    'services/sql_executor.py': ['core.gen_sql', 'core.gen_chat', 'app.routers'],
    'core/ret_retriever.py': ['app.permissions', 'app.routers'],
    'services/sql_gateway.py': ['services.sql_executor', 'core.gen_sql',
                                'core.gen_chat', 'app.routers'],
    'core/gen_chat.py': ['services.sql_executor', 'app.routers'],
    'core/recall_scope.py': ['core.ret_retriever', 'app.routers'],
}

# 全局规则：业务模块（core/ + services/）一律不得反向依赖路由层
GLOBAL_FORBIDDEN_PREFIX = 'app.routers'


def _collect_imports(py_file: Path):
    """返回文件内所有 import 的模块名（含 import x.y.z 与 from x.y import ...）"""
    tree = ast.parse(py_file.read_text(encoding='utf-8'))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _violates(imported: str, forbidden: list) -> str:
    """imported 是否命中禁止前缀（按点分段精确匹配，防 sql_executor 误伤 sql_exec）"""
    for f in forbidden:
        parts = f.split('.')
        segs = imported.split('.')
        if segs[:len(parts)] == parts:
            return f
    return ''


def test_no_forbidden_import_edges():
    violations = []
    for rel, forbidden in FORBIDDEN_EDGES.items():
        py = ROOT / rel
        assert py.exists(), f'红线目标文件不存在: {rel}'
        for mod in _collect_imports(py):
            hit = _violates(mod, forbidden)
            if hit:
                violations.append(f'{rel} imports {mod} (命中红线: {hit})')
    assert not violations, '模块依赖红线被破坏：\n' + '\n'.join(violations)


def test_business_modules_never_import_routers():
    violations = []
    for dir_name in ('core', 'services'):
        for py in (ROOT / dir_name).glob('*.py'):
            for mod in _collect_imports(py):
                if _violates(mod, [GLOBAL_FORBIDDEN_PREFIX]):
                    violations.append(f'{dir_name}/{py.name} imports {mod}')
    assert not violations, '业务模块反向依赖路由层：\n' + '\n'.join(violations)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
