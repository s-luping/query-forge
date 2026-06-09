"""权限校验 — admin/user 两级，直接查用户表"""
from models import AppSessionLocal
from models.user import UserSchema, UserExtra


def is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def get_visible_schema_names(user: dict) -> list:
    """获取用户可见的 schema_name 列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    db = AppSessionLocal()
    try:
        records = db.query(UserSchema).filter(UserSchema.user_id == user['user_id']).all()
        if not records:
            return []
        names = [r.schema_name for r in records]
        if None in names:
            return None
        return names
    finally:
        db.close()


def get_visible_extra_ids(user: dict) -> list:
    """获取用户可见的补充知识ID列表。None=全部。[]=无。"""
    if is_admin(user):
        return None
    db = AppSessionLocal()
    try:
        records = db.query(UserExtra).filter(UserExtra.user_id == user['user_id']).all()
        if not records:
            return []
        ids = [r.extra_id for r in records]
        if None in ids:
            return None
        return ids
    finally:
        db.close()
