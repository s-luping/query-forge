# -*- coding: UTF-8 -*-
"""验证 get_visible_schema_ids 的数据源门控 + 超管兜底语义。"""
import sqlite3
import sys
sys.path.insert(0, r'D:\projects\query-forge')

from app.permissions import get_visible_schema_ids
from crud.base import session_scope
from models.role import RolePermission, UserRole

TEST_UID = 999
ADMIN_UID = 1
DB = r'D:\projects\query-forge\db\queryforge.db'


def raw(sql):
    c = sqlite3.connect(DB)
    c.execute('PRAGMA foreign_keys=ON')
    c.execute(sql)
    c.commit()
    c.close()


def set_user_roles(role_ids):
    with session_scope() as db:
        db.query(UserRole).filter(UserRole.user_id == TEST_UID).delete()
        for rid in role_ids:
            db.add(UserRole(user_id=TEST_UID, role_id=rid))
        db.commit()


def set_role_perms(role_id, items):
    with session_scope() as db:
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for it in items:
            db.add(RolePermission(role_id=role_id, permission_code='access', **it))
        db.commit()


# 准备一个临时真实用户，满足 user_roles 外键
raw("INSERT OR IGNORE INTO users (id,username,password,is_active) VALUES (999,'__test_vis','x',1)")

# (名称, 用户role, 测试用户绑定角色, 操作角色id, 授权记录, 期望可见库id列表)
scenarios = [
    ('仅 schema ALLOW(库1)，未配数据源', 'user', [2], 2,
     [{'resource_type': 'schema', 'resource_id': 1, 'access_type': 'ALLOW'}], []),
    ('仅 datasource ALLOW(1)', 'user', [2], 2,
     [{'resource_type': 'datasource', 'resource_id': 1, 'access_type': 'ALLOW'}], [1]),
    ('datasource ALLOW(NULL) 全量', 'user', [2], 2,
     [{'resource_type': 'datasource', 'resource_id': None, 'access_type': 'ALLOW'}], [1]),
    ('schema ALLOW(1)+datasource ALLOW(1)', 'user', [2], 2,
     [{'resource_type': 'schema', 'resource_id': 1, 'access_type': 'ALLOW'},
      {'resource_type': 'datasource', 'resource_id': 1, 'access_type': 'ALLOW'}], [1]),
    ('schema DENY(1)+datasource ALLOW(1)', 'user', [2], 2,
     [{'resource_type': 'schema', 'resource_id': 1, 'access_type': 'DENY'},
      {'resource_type': 'datasource', 'resource_id': 1, 'access_type': 'ALLOW'}], []),
    ('schema DENY(NULL)+datasource ALLOW(1)', 'user', [2], 2,
     [{'resource_type': 'schema', 'resource_id': None, 'access_type': 'DENY'},
      {'resource_type': 'datasource', 'resource_id': 1, 'access_type': 'ALLOW'}], []),
    ('管理员 无授权（超管兜底）', 'admin', None, 1, [], [1]),
    ('普通用户 无授权（默认拒绝）', 'user', [2], 2, [], []),
]

all_ok = True
for name, role, roles_for_uid, rid, perms, expect in scenarios:
    if roles_for_uid is not None:
        set_user_roles(roles_for_uid)
    set_role_perms(rid, perms)
    uid = ADMIN_UID if role == 'admin' else TEST_UID
    res = get_visible_schema_ids({'user_id': uid, 'role': role})
    ok = (res == expect)
    all_ok = all_ok and ok
    print(('PASS' if ok else 'FAIL'), name, '=>', res, '(expect', expect, ')')

# 清理临时数据，避免污染真实库
set_user_roles([])
set_role_perms(1, [])
set_role_perms(2, [])
raw('DELETE FROM users WHERE id=999')
print('RESULT:', 'ALL OK' if all_ok else 'SOME FAILED')
