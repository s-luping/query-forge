# -*- coding: UTF-8 -*-
"""数据库引擎与会话工厂 — 双库布局（主库 + LLM 遥测库）

并发策略（针对历史"查看记录被其他进程卡住"问题的系统性修复）：
- 两库均启用 WAL（读不阻塞写、写不阻塞读，仅写-写串行）
- busy_timeout=5000 全引擎生效（写锁竞争时等待而非立刻失败）
- synchronous=NORMAL（WAL 下的安全性与性能平衡点）
- 主库开启 FOREIGN KEY 约束
- 业务代码保持短事务：一个请求内多次小 commit，避免长事务持锁
"""
import os
import time
from datetime import datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.config import (
    MAIN_DB_PATH,
    TELEMETRY_DB_PATH,
    SYSTEM_SETTING_DEFAULTS,
    initialize_runtime_secrets,
)
from app.logger import logger
from app.timezone import now_beijing


def _make_pragma(foreign_keys: bool):
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")
        if foreign_keys:
            cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    return _set_sqlite_pragma


def _create_engine_with_wal(db_path: str, foreign_keys: bool = False):
    engine = create_engine(
        f'sqlite:///{db_path}',
        echo=False,
        connect_args={'check_same_thread': False, 'timeout': 30}
    )
    event.listen(engine, 'connect', _make_pragma(foreign_keys))
    return engine


def _ensure_db_dirs():
    for db_path in [MAIN_DB_PATH, TELEMETRY_DB_PATH]:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"创建数据库目录: {db_dir}")


_ensure_db_dirs()

# 主库：交互域（短事务）
engine_main = _create_engine_with_wal(MAIN_DB_PATH, foreign_keys=True)
# 遥测库：LLM 调用追加型高频写
engine_telemetry = _create_engine_with_wal(TELEMETRY_DB_PATH)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
TelemetrySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_telemetry)


# ═══════════════════════════════════════════════════════════════════
# 初始化与种子数据
# ═══════════════════════════════════════════════════════════════════

def _seed_system_settings():
    from models.system import SystemSetting

    db = SessionLocal()
    try:
        for key, (default_value, category, editable) in SYSTEM_SETTING_DEFAULTS.items():
            if db.query(SystemSetting).filter(SystemSetting.key == key).first():
                continue
            db.add(SystemSetting(key=key, value=default_value,
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


def init_database():
    """初始化双库表结构 + 种子数据"""
    initialize_runtime_secrets()
    from models.base import MainBase, TelemetryBase
    # 触发所有模型注册
    from models import user, role, schema, knowledge, conversation, llm, system, vector_index, security, sync  # noqa: F401

    MainBase.metadata.create_all(engine_main)
    TelemetryBase.metadata.create_all(engine_telemetry)
    logger.info(f"主库表创建/检查完成: {MAIN_DB_PATH}")
    logger.info(f"遥测库表创建/检查完成: {TELEMETRY_DB_PATH}")

    _seed_system_settings()
    create_default_admin()
    _seed_roles()
