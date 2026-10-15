# -*- coding: UTF-8 -*-
"""验证直接修改 config.py 切换数据库（不使用 .env 文件）"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_default_sqlite():
    """Test 1: DATABASE_URL = '' 时默认 SQLite"""
    import app.config as config
    config.DATABASE_URL = ''
    config.TELEMETRY_DATABASE_URL = ''

    from db.engine import _resolve_urls
    main_url, tel_url = _resolve_urls()
    assert main_url.startswith('sqlite')
    assert tel_url.startswith('sqlite')
    assert main_url != tel_url, 'SQLite should have separate files'
    print('  PASS: SQLite default, main != telemetry (separate files)')


def test_mysql():
    """Test 2: DATABASE_URL = MySQL 连接串"""
    import app.config as config
    config.DATABASE_URL = 'mysql+pymysql://testuser:testpass@testhost:3306/testdb?charset=utf8mb4'
    config.TELEMETRY_DATABASE_URL = ''

    from db.engine import _is_sqlite_url, _mask_url, _resolve_urls
    assert not _is_sqlite_url(config.DATABASE_URL)
    main_url, tel_url = _resolve_urls()
    assert main_url == config.DATABASE_URL
    assert tel_url == main_url, 'MySQL: telemetry should = main'
    masked = _mask_url(main_url)
    assert 'testpass' not in masked
    assert '***' in masked
    print(f'  PASS: MySQL, masked={masked}, telemetry=main')


def test_postgresql():
    """Test 3: DATABASE_URL = PostgreSQL 连接串"""
    import app.config as config
    config.DATABASE_URL = 'postgresql+psycopg2://pguser:pgpass@10.0.0.1:5432/queryforge'
    config.TELEMETRY_DATABASE_URL = ''

    from db.engine import _resolve_urls
    main_url, tel_url = _resolve_urls()
    assert main_url == config.DATABASE_URL
    assert tel_url == main_url
    print('  PASS: PostgreSQL, telemetry=main')


def test_sqlite_explicit():
    """Test 4: DATABASE_URL 显式指定 SQLite 路径"""
    import app.config as config
    config.DATABASE_URL = 'sqlite:///db/test_explicit.db'
    config.TELEMETRY_DATABASE_URL = ''

    from db.engine import _is_sqlite_url, _resolve_urls
    assert _is_sqlite_url(config.DATABASE_URL)
    main_url, tel_url = _resolve_urls()
    assert 'test_explicit' in main_url
    assert tel_url != main_url, 'SQLite: telemetry should be separate'
    print('  PASS: explicit SQLite, telemetry=separate file')


def test_separate_telemetry():
    """Test 5: 同时指定主库和遥测库"""
    import app.config as config
    config.DATABASE_URL = 'mysql+pymysql://u1:p1@h1:3306/main_db?charset=utf8mb4'
    config.TELEMETRY_DATABASE_URL = 'mysql+pymysql://u2:p2@h2:3306/telemetry_db?charset=utf8mb4'

    from db.engine import _resolve_urls
    main_url, tel_url = _resolve_urls()
    assert 'main_db' in main_url
    assert 'telemetry_db' in tel_url
    assert main_url != tel_url
    print('  PASS: separate main+telemetry URLs')


def test_back_to_default():
    """Test 6: 清空 DATABASE_URL 后回到默认 SQLite"""
    import app.config as config
    config.DATABASE_URL = ''
    config.TELEMETRY_DATABASE_URL = ''

    from db.engine import _resolve_urls
    main_url, _ = _resolve_urls()
    assert main_url.startswith('sqlite')
    assert 'queryforge.db' in main_url
    print('  PASS: back to default SQLite')


if __name__ == '__main__':
    print('=== Config-Only DB Switch Verification ===\n')
    tests = [
        ('Default SQLite (DATABASE_URL = "")', test_default_sqlite),
        ('MySQL via config.py', test_mysql),
        ('PostgreSQL via config.py', test_postgresql),
        ('Explicit SQLite via config.py', test_sqlite_explicit),
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
    print(f'\n=== {passed}/{len(tests)} tests PASSED ===')
