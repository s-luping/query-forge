# -*- coding: UTF-8 -*-
"""数据库引擎与会话工厂 — 双库布局（主库 + LLM 遥测库）

数据库模式自动切换：
  1) SQLite（默认，适合个人/小型项目）：零配置，WAL + busy_timeout + 连接池
  2) 外部数据库（MySQL/PostgreSQL，适合团队/企业）：通过 DATABASE_URL 环境变量启用
     外部数据库自动跳过 SQLite PRAGMA，使用原生连接池

并发策略（SQLite 场景）：
- WAL（读不阻塞写、写不阻塞读，仅写-写串行）
- busy_timeout=5000（写锁竞争时等待而非立刻失败）
- synchronous=NORMAL（WAL 下的安全性与性能平衡点）
- 主库开启 FOREIGN KEY 约束

连接池复用（SQLAlchemy QueuePool）：
- 主库 / 遥测库各自独立的连接池
- 连接复用避免高频短事务场景下反复建立连接的损耗
- pool_recycle 定期回收，防止陈旧连接
"""
import os
import secrets
import string
import time
from urllib.parse import urlparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

import app.config as config
from app.config import (
    DATABASE_URL, TELEMETRY_DATABASE_URL,
    MAIN_DB_PATH, TELEMETRY_DB_PATH,
    DB_IS_SQLITE,
)
from app.logger import logger
from app.timezone import now_beijing


def _make_pragma(foreign_keys: bool):
    """SQLite 专用 PRAGMA 钩子 — 仅在 SQLite 引擎上注册"""
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA mmap_size=268435456")   # 256MB 内存映射
        cursor.execute("PRAGMA temp_store=MEMORY")
        if foreign_keys:
            cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    return _set_sqlite_pragma


def _create_engine(db_url: str, *, foreign_keys: bool = False, is_sqlite: bool = True,
                   db_path: str = ''):
    """创建数据库引擎 — 统一入口，支持 SQLite 和外部数据库

    SQLite: WAL + PRAGMA + check_same_thread=False
    MySQL/PostgreSQL: 原生连接池，无 PRAGMA
    """
    engine_kwargs = dict(
        echo=config.DB_ECHO,
        poolclass=QueuePool,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        pool_timeout=config.DB_POOL_TIMEOUT,
        pool_recycle=config.DB_POOL_RECYCLE,
    )

    if is_sqlite:
        engine_kwargs['connect_args'] = {'check_same_thread': False, 'timeout': 30}
        engine = create_engine(db_url, **engine_kwargs)
        event.listen(engine, 'connect', _make_pragma(foreign_keys))
    else:
        # 外部数据库：MySQL/PostgreSQL 连接池参数
        # MySQL 默认连接数有限，适当控制 pool_size
        engine = create_engine(db_url, **engine_kwargs)

    dialect = db_url.split('://')[0].split('+')[0]
    logger.info(f"数据库引擎已创建: dialect={dialect}, url={_mask_password(db_url)}")
    return engine


def _mask_password(url: str) -> str:
    """隐藏 URL 中的密码用于日志输出"""
    if '://' not in url:
        return url
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, '***')
    except Exception:
        pass
    return url


def _ensure_db_dirs():
    """确保 SQLite 数据库目录存在（外部数据库跳过）"""
    if not DB_IS_SQLITE:
        return
    for db_path in [MAIN_DB_PATH, TELEMETRY_DB_PATH]:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"创建数据库目录: {db_dir}")


_ensure_db_dirs()

# ── 创建双库引擎 ──────────────────────────────────────────
if DB_IS_SQLITE:
    _main_url = f'sqlite:///{MAIN_DB_PATH}'
    _telemetry_url = f'sqlite:///{TELEMETRY_DB_PATH}'
else:
    _main_url = DATABASE_URL
    _telemetry_url = TELEMETRY_DATABASE_URL or DATABASE_URL

engine_main = _create_engine(_main_url, foreign_keys=True, is_sqlite=DB_IS_SQLITE)
engine_telemetry = _create_engine(
    _telemetry_url,
    foreign_keys=False,
    is_sqlite=not TELEMETRY_DATABASE_URL or TELEMETRY_DATABASE_URL.startswith('sqlite'),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
TelemetrySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_telemetry)


def get_setting(key: str, default: str = '') -> str:
    """读取系统配置：数据库 system_settings 优先（前台用户改过的值），
    其次回落 config 中同名变量的初始值；都没有则返回 default。"""
    from models.system import SystemSetting
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row is not None and str(row.value) not in ('', 'None'):
            return str(row.value)
    finally:
        db.close()
    return str(getattr(config, key, '') or default)


# ═══════════════════════════════════════════════════════════════════
# 初始化与种子数据
# ═══════════════════════════════════════════════════════════════════

# 系统设置种子元信息：key -> (分类, 是否可编辑)
# 初始值统一取自 app/config.py 中的同名变量（config 包含全部变量初始值）。
SETTING_META = {
    'SECRET_KEY': ('security', 0),
    'ACCESS_TOKEN_EXPIRE_MINUTES': ('auth', 1),
    'ALLOW_REGISTER': ('auth', 1),
    'EMBEDDING_MODEL_READY': ('runtime', 0),
    'EMBEDDING_MODEL_PATH': ('runtime', 0),
    'VECTOR_INDEX_THRESHOLD': ('vector', 1),
    'FIELD_RECALL_TOP_K': ('vector', 1),
    'MAX_TABLES': ('vector', 1),
}


def _seed_system_settings():
    from models.system import SystemSetting

    db = SessionLocal()
    try:
        for key, (category, editable) in SETTING_META.items():
            if db.query(SystemSetting).filter(SystemSetting.key == key).first():
                continue
            value = str(getattr(config, key, '') or '')
            # 密钥类：config 未配置时首次初始化自动生成随机字符串并持久化
            if key == 'SECRET_KEY' and not value:
                value = secrets.token_urlsafe(36)
            db.add(SystemSetting(key=key, value=value,
                                 category=category, is_editable=editable))
            logger.info(f"已初始化系统配置 {key} (category={category})")
        db.commit()
    except Exception as e:
        logger.warning(f"初始化系统配置失败: {e}")
        db.rollback()
    finally:
        db.close()


def _seed_roles():
    from models.role import Role, UserRole
    from models.user import User

    db = SessionLocal()
    try:
        admin_role = db.query(Role).filter(Role.code == 'admin').first()
        if not admin_role:
            admin_role = Role(name='管理员', code='admin', description='系统全部权限', is_system=1)
            db.add(admin_role)
            db.flush()
        user_role = db.query(Role).filter(Role.code == 'user').first()
        if not user_role:
            user_role = Role(name='普通用户', code='user', description='默认用户权限', is_system=1)
            db.add(user_role)
            db.flush()
        admin = db.query(User).filter(User.role == 'admin').first()
        if admin and not db.query(UserRole).filter(
                UserRole.user_id == admin.id, UserRole.role_id == admin_role.id).first():
            db.add(UserRole(user_id=admin.id, role_id=admin_role.id))
        for item in db.query(User).filter(User.role != 'admin').all():
            if not db.query(UserRole).filter(UserRole.user_id == item.id).first():
                db.add(UserRole(user_id=item.id, role_id=user_role.id))
        db.commit()
    except Exception as e:
        logger.warning(f"初始化角色失败: {e}")
        db.rollback()
    finally:
        db.close()


def create_default_admin():
    from models.user import User

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == 'admin').first()
        if not admin:
            from app.auth import hash_password
            chars = string.ascii_letters + string.digits + '!@#$%^&*'
            pwd = ''.join(secrets.choice(chars) for _ in range(16))
            db.add(User(
                username='admin', password=hash_password(pwd), role='admin',
                description='系统管理员', is_active=1,
                pwd_ts=time.time(), register_date=now_beijing()
            ))
            db.commit()
            logger.info("默认管理员用户创建成功: admin")
            print(f"\n{'='*60}")
            print(f"  默认管理员账号已创建")
            print(f"  用户名: admin")
            print(f"  密码:   {pwd}")
            print(f"  请登录后立即修改密码！")
            print(f"{'='*60}\n")
        else:
            logger.debug("管理员用户已存在")
    except Exception as e:
        logger.error(f"创建默认用户失败: {e}")
        db.rollback()
    finally:
        db.close()


def _ensure_column_sqlite(db_path: str, table: str, column: str, ddl: str) -> None:
    """轻量迁移：SQLite 已存在的表补列（幂等，重复执行无害）"""
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(db_path)
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
            if column not in cols:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
                conn.commit()
                logger.info(f"迁移: {table} 新增列 {column}")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"迁移失败 {table}.{column}: {e}")


def _ensure_column_generic(table: str, column: str, ddl: str) -> None:
    """通用迁移：通过 SQLAlchemy 检查并补列（MySQL/PostgreSQL）"""
    try:
        from sqlalchemy import inspect as sqla_inspect
        inspector = sqla_inspect(engine_main)
        if table not in inspector.get_table_names():
            return
        cols = [c['name'] for c in inspector.get_columns(table)]
        if column not in cols:
            with engine_main.connect() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
                conn.commit()
            logger.info(f"迁移: {table} 新增列 {column}")
    except Exception as e:
        logger.warning(f"迁移失败 {table}.{column}: {e}")


def init_database():
    """初始化双库表结构 + 种子数据"""
    from models.base import MainBase, TelemetryBase
    # 触发所有模型注册
    from models import user, role, schema, knowledge, conversation, llm, system, vector_index, security, sync, datasource  # noqa: F401

    MainBase.metadata.create_all(engine_main)
    TelemetryBase.metadata.create_all(engine_telemetry)

    # 轻量迁移：历史库补列（按数据库类型选择方式）
    if DB_IS_SQLITE:
        _ensure_column_sqlite(MAIN_DB_PATH, 'conversation_messages', 'result_data', 'TEXT')
    else:
        _ensure_column_generic('conversation_messages', 'result_data', 'TEXT')

    _main_desc = _main_url if not DB_IS_SQLITE else MAIN_DB_PATH
    _telemetry_desc = _telemetry_url if not (DB_IS_SQLITE and not TELEMETRY_DATABASE_URL) else TELEMETRY_DB_PATH
    logger.info(f"主库表创建/检查完成: {_mask_password(_main_desc)}")
    logger.info(f"遥测库表创建/检查完成: {_mask_password(_telemetry_desc)}")

    _seed_system_settings()
    create_default_admin()
    _seed_roles()
