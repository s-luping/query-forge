# -*- coding: UTF-8 -*-
"""重置管理员密码 — 直接改数据库，用于遗忘密码时恢复访问。

用法：
    python scripts/admin_account_reset.py                     # 交互式输入新密码
    python scripts/admin_account_reset.py --password 新密码   # 命令行指定
    python scripts/admin_account_reset.py --username admin --password 新密码

说明：
    - 默认重置用户名为 admin 的账号，可用 --username 指定其他用户；
    - 新密码使用 bcrypt 哈希后写入，并刷新 pwd_ts，使该用户所有旧登录 token 立即失效；
    - 目标用户不存在时默认直接创建（角色 admin，相当于找回入口），
      若只想重置不想创建，可加 --no-create。
"""
import argparse
import getpass
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description='重置管理员密码')
    parser.add_argument('--username', default='admin', help='目标用户名（默认 admin）')
    parser.add_argument('--password', help='新密码；不指定则交互式输入')
    parser.add_argument('--no-create', action='store_true',
                        help='用户不存在时仅报错，不自动创建')
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        print('用户名不能为空')
        return 1

    password = args.password
    if not password:
        password = getpass.getpass(f'请输入 {username} 的新密码: ')
        if not password:
            print('密码不能为空')
            return 1
        confirm = getpass.getpass('请再次输入确认: ')
        if password != confirm:
            print('两次输入的密码不一致')
            return 1

    from app.security import hash_password
    from crud.base import session_scope
    from models.user import User

    with session_scope() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            if args.no_create:
                print(f'用户 {username} 不存在（已指定 --no-create，不自动创建）')
                return 1
            from app.timezone import now_beijing
            user = User(
                username=username,
                password=hash_password(password),
                role='admin',
                description='系统管理员（脚本重置时创建）',
                is_active=1,
                pwd_ts=time.time(),
                register_date=now_beijing(),
            )
            db.add(user)
            print(f'用户 {username} 不存在，已自动创建为管理员')
        else:
            user.password = hash_password(password)
            user.pwd_ts = time.time()  # 刷新密码时间戳，撤销该用户所有旧 token
            print(f'用户 {username} 密码已重置')

    print('=' * 50)
    print(f'  用户名: {username}')
    print(f'  新密码: {password}')
    print('  请使用新密码登录，旧登录态已全部失效！')
    print('=' * 50)
    return 0


if __name__ == '__main__':
    sys.exit(main())
