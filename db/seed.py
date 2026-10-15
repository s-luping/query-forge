# -*- coding: UTF-8 -*-
"""种子数据 — 系统配置、默认管理员、角色

所有数据库类型通用：init_database() 调用时无论 SQLite / MySQL / PostgreSQL
都执行相同的种子逻辑。
"""
import secrets
import string
import time

from app.logger import logger
from app.timezone import now_beijing

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
    """初始化系统配置表 — 从 config 初始值写入 system_settings"""
    import app.config as config
    from db.engine import SessionLocal
    from models.system import SystemSetting
    db = SessionLocal()
    try:
        for key, (category, editable) in SETTING_META.items():
            if db.query(SystemSetting).filter(SystemSetting.key == key).first():
                continue
            value = str(getattr(config, key, '') or '')
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
    """初始化角色 — 管理员 / 普通用户，并为已有用户分配角色"""
    from db.engine import SessionLocal
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
    """创建默认管理员用户（仅首次）"""
    from app.auth import hash_password
    from db.engine import SessionLocal
    from models.user import User
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == 'admin').first()
        if not admin:
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
            print("  默认管理员账号已创建")
            print("  用户名: admin")
            print(f"  密码:   {pwd}")
            print("  请登录后立即修改密码！")
            print(f"{'='*60}\n")
        else:
            logger.debug("管理员用户已存在")
    except Exception as e:
        logger.error(f"创建默认用户失败: {e}")
        db.rollback()
    finally:
        db.close()
