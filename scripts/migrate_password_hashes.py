# -*- coding: UTF-8 -*-
"""一次性迁移：将 users 表中的明文密码升级为 bcrypt 哈希

用法（项目根目录）:
    .venv/Scripts/python.exe scripts/migrate_password_hashes.py

- 已是哈希（$2 开头）的行跳过
- 迁移前自动备份 db/queryforge.db -> db/queryforge.db.bak-pwd-<日期>
- 同时为所有用户初始化 pwd_ts（撤销历史 token）
"""
import os
import shutil
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402
from app.auth import hash_password, is_hashed  # noqa: E402


def main():
    # 先补齐 users.pwd_ts 列（与应用启动时的轻量迁移同源）
    from models.database import _migrate_columns
    _migrate_columns()

    db = SessionLocal()
    try:
        users = db.query(User).all()
        migrated = skipped = 0
        for u in users:
            if is_hashed(u.password or ''):
                skipped += 1
            else:
                u.password = hash_password(u.password)
                migrated += 1
            # 统一初始化 pwd_ts，撤销所有存量 token（迁移后需重新登录）
            if not u.pwd_ts:
                u.pwd_ts = time.time()
        db.commit()
        print(f"完成: 哈希迁移 {migrated} 个用户, 已是哈希跳过 {skipped} 个")
        print("注意: 所有存量 token 已失效，全部用户需重新登录")
    except Exception as e:
        db.rollback()
        print(f"迁移失败(已回滚): {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    # 迁移前备份
    from app.config import MAIN_DB_PATH
    bak = f"{MAIN_DB_PATH}.bak-pwd-{date.today().strftime('%Y%m%d')}"
    if os.path.exists(MAIN_DB_PATH) and not os.path.exists(bak):
        shutil.copy2(MAIN_DB_PATH, bak)
        print(f"已备份: {bak}")
    main()
