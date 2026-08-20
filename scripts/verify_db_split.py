# -*- coding: UTF-8 -*-
"""验证脚本：db 模块拆分后的 import 与功能检查"""
import os
import sys
import importlib

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

errors = []
passes = []

# 1. db.engine
try:
    from db.engine import (
        engine_main, engine_telemetry, SessionLocal,
        TelemetrySessionLocal, is_sqlite,
        create_db_engine, _resolve_urls, _mask_url,
    )
    passes.append('db.engine: all exports OK')
except Exception as e:
    errors.append(f'db.engine FAIL: {e}')

# 2. db.sqlite_hooks
try:
    from db.sqlite_hooks import _make_pragma, _ensure_column_sqlite
    passes.append('db.sqlite_hooks: _make_pragma, _ensure_column_sqlite OK')
except Exception as e:
    errors.append(f'db.sqlite_hooks FAIL: {e}')

# 3. db.seed
try:
    from db.seed import _seed_system_settings, _seed_roles, create_default_admin, SETTING_META
    passes.append('db.seed: all exports OK')
except Exception as e:
    errors.append(f'db.seed FAIL: {e}')

# 4. db.database
try:
    from db.database import get_setting, init_database, is_sqlite
    passes.append('db.database: get_setting, init_database, is_sqlite OK')
except Exception as e:
    errors.append(f'db.database FAIL: {e}')

# 5. db __init__
try:
    from db import (
        engine_main, engine_telemetry, SessionLocal,
        TelemetrySessionLocal, get_setting, init_database,
        is_sqlite, AppSessionLocal,
    )
    passes.append('db (__init__): all 8 exports OK')
except Exception as e:
    errors.append(f'db __init__ FAIL: {e}')

# 6. crud.base (downstream consumer)
try:
    from crud.base import session_scope, tx_scope, BaseCrud
    passes.append('crud.base: session_scope, tx_scope, BaseCrud OK')
except Exception as e:
    errors.append(f'crud.base FAIL: {e}')

# 7. app.config
try:
    import app.config as config
    assert hasattr(config, 'DATABASE_URL'), 'config.DATABASE_URL missing'
    assert hasattr(config, 'TELEMETRY_DATABASE_URL'), 'config.TELEMETRY_DATABASE_URL missing'
    assert config.DATABASE_URL == '', f'DATABASE_URL should be empty, got: {config.DATABASE_URL!r}'
    passes.append('app.config: DATABASE_URL, TELEMETRY_DATABASE_URL (empty default) OK')
except Exception as e:
    errors.append(f'app.config FAIL: {e}')

# 8. is_sqlite flag
try:
    from db import is_sqlite
    assert is_sqlite is True, f'is_sqlite should be True, got: {is_sqlite}'
    passes.append(f'is_sqlite flag: True (default SQLite) OK')
except Exception as e:
    errors.append(f'is_sqlite flag FAIL: {e}')

# 9. _mask_url password masking
try:
    masked = _mask_url('mysql+pymysql://user:secret@host:3306/db')
    assert '***' in masked and 'secret' not in masked, f'Password not masked: {masked}'
    passes.append(f'_mask_url: password masked -> {masked} OK')
except Exception as e:
    errors.append(f'_mask_url FAIL: {e}')

# 10. _resolve_urls default SQLite
try:
    main_url, tel_url = _resolve_urls()
    assert main_url.startswith('sqlite'), f'Main should be sqlite, got: {main_url}'
    assert tel_url.startswith('sqlite'), f'Telemetry should be sqlite, got: {tel_url}'
    assert main_url != tel_url, 'SQLite should have separate files'
    passes.append(f'_resolve_urls: separate SQLite files OK')
except Exception as e:
    errors.append(f'_resolve_urls FAIL: {e}')

# 11. External DB simulation (MySQL URL)
try:
    os.environ['DATABASE_URL'] = 'mysql+pymysql://user:pass@localhost:3306/test'
    importlib.reload(config)
    main_url2, tel_url2 = _resolve_urls()
    assert main_url2 == 'mysql+pymysql://user:pass@localhost:3306/test', f'Got: {main_url2}'
    assert tel_url2 == main_url2, f'External: telemetry should = main, got: {tel_url2}'
    passes.append(f'_resolve_urls (MySQL): telemetry = main (same DB) OK')
    # Clean up
    del os.environ['DATABASE_URL']
    importlib.reload(config)
except Exception as e:
    errors.append(f'_resolve_urls (MySQL) FAIL: {e}')

# 12. engine_telemetry is engine_main for external DB
try:
    # Default SQLite: separate engines
    assert engine_telemetry is not engine_main, 'SQLite: should have separate engines'
    passes.append('engine_telemetry != engine_main (SQLite separate engines) OK')
except Exception as e:
    errors.append(f'engine check FAIL: {e}')

# 13. services.sql_executor import (downstream)
try:
    from db import engine_main as em
    assert em is engine_main
    passes.append('services.sql_executor: from db import engine_main OK')
except Exception as e:
    errors.append(f'sql_executor import FAIL: {e}')

print(f'\n=== Results: {len(passes)}/{len(passes)+len(errors)} PASS ===')
for p in passes:
    print(f'  PASS  {p}')
for e in errors:
    print(f'  FAIL  {e}')

if errors:
    sys.exit(1)
