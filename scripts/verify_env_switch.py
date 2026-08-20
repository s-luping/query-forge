# -*- coding: UTF-8 -*-
"""验证 .env 加载与数据库切换（不触发实际引擎创建，仅测试 URL 解析）"""
import os
import sys
import importlib

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

ENV_FILE = os.path.join(PROJECT_ROOT, '.env')


def _clear_env():
    with open(ENV_FILE, 'w') as f:
        f.write('')
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('TELEMETRY_DATABASE_URL', None)


def _write_env(content):
    with open(ENV_FILE, 'w') as f:
        f.write(content)


def _reload_config():
    import app.config as config
    importlib.reload(config)
    return config


def test_default_sqlite():
    """Test 1: 空 .env = 默认 SQLite"""
    _clear_env()
    config = _reload_config()
    assert config.DATABASE_URL == ''

    from db.engine import _resolve_urls, _is_sqlite_url, _mask_url
    main_url, tel_url = _resolve_urls()
    assert main_url.startswith('sqlite')
    assert tel_url.startswith('sqlite')
    assert main_url != tel_url
    print(f'  PASS: SQLite default, main != telemetry (separate files)')


def test_mysql_url():
    """Test 2: .env 配置 MySQL"""
    _write_env('DATABASE_URL=mysql+pymysql://testuser:testpass@testhost:3306/testdb?charset=utf8mb4\n')
    config = _reload_config()
    assert config.DATABASE_URL == 'mysql+pymysql://testuser:testpass@testhost:3306/testdb?charset=utf8mb4'

    from db.engine import _resolve_urls, _is_sqlite_url, _mask_url
    assert not _is_sqlite_url(config.DATABASE_URL)
    main_url, tel_url = _resolve_urls()
    assert main_url == config.DATABASE_URL
    assert tel_url == main_url, 'MySQL: telemetry should = main'
    masked = _mask_url(main_url)
    assert 'testpass' not in masked
    assert '***' in masked
    print(f'  PASS: MySQL .env loaded, masked={masked}, telemetry=main')


def test_postgresql_url():
    """Test 3: .env 配置 PostgreSQL"""
    _write_env('DATABASE_URL=postgresql+psycopg2://pguser:pgpass@10.0.0.1:5432/queryforge\n')
    config = _reload_config()
    assert config.DATABASE_URL.startswith('postgresql')

    from db.engine import _resolve_urls
    main_url, tel_url = _resolve_urls()
    assert main_url == config.DATABASE_URL
    assert tel_url == main_url
    print(f'  PASS: PostgreSQL .env loaded, telemetry=main')


def test_sqlite_explicit():
    """Test 4: .env 显式 SQLite"""
    _write_env('DATABASE_URL=sqlite:///db/test_explicit.db\n')
    config = _reload_config()

    from db.engine import _resolve_urls, _is_sqlite_url
    assert _is_sqlite_url(config.DATABASE_URL)
    main_url, tel_url = _resolve_urls()
    assert 'test_explicit' in main_url
    assert tel_url != main_url, 'SQLite: telemetry should be separate'
    print(f'  PASS: explicit SQLite, telemetry=separate file')


def test_separate_telemetry():
    """Test 5: .env 同时指定主库和遥测库"""
    _write_env(
        'DATABASE_URL=mysql+pymysql://u1:p1@h1:3306/main_db?charset=utf8mb4\n'
        'TELEMETRY_DATABASE_URL=mysql+pymysql://u2:p2@h2:3306/telemetry_db?charset=utf8mb4\n'
    )
    config = _reload_config()

    from db.engine import _resolve_urls, _mask_url
    main_url, tel_url = _resolve_urls()
    assert 'main_db' in main_url
    assert 'telemetry_db' in tel_url
    assert main_url != tel_url
    print(f'  PASS: separate main+telemetry URLs')


def test_back_to_default():
    """Test 6: 清空 .env 后回到默认"""
    _clear_env()
    config = _reload_config()
    assert config.DATABASE_URL == ''

    from db.engine import _resolve_urls
    main_url, _ = _resolve_urls()
    assert main_url.startswith('sqlite')
    assert 'queryforge.db' in main_url
    print(f'  PASS: back to default SQLite')


if __name__ == '__main__':
    print('=== .env Loading & DB Switch Verification ===\n')
    tests = [
        ('Default SQLite (empty .env)', test_default_sqlite),
        ('MySQL via .env', test_mysql_url),
        ('PostgreSQL via .env', test_postgresql_url),
        ('Explicit SQLite via .env', test_sqlite_explicit),
        ('Separate telemetry URL', test_separate_telemetry),
        ('Back to default SQLite', test_back_to_default),
    ]
    passed = 0
    for name, fn in tests:
        print(f'Test: {name}')
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f'  FAIL: {e}')
    _clear_env()
    _reload_config()
    print(f'\n=== {passed}/{len(tests)} tests PASSED ===')
