"""知识库模型 — 表名 knowledge_items

字段语义：
- content: 自由文本知识（业务口径/表关系/计算规则等），向后兼容，生成 SQL 时注入提示词。
           对 typed 条目可留空或作为人类可读摘要。
- knowledge_type: 知识类型（平台不解释具体值，仅做路由/渲染）。
   内置类型：note(普通笔记/自由文本) / terminology(术语别名) / calculation(计算规则)
            / relation(表关系) / value_domain(取值域) / convention(约定)
            / entity_map(实体映射) / sample_qa(样例问答) / quality(数据质量/清洗陷阱)
- aliases: 同义词/别名 JSON 数组字符串，用于召回增强（命中别名即召回该条目）。
- payload: 结构化内容 JSON 字符串，按 knowledge_type 解释，平台只透传 + 内建类型渲染。
- scope_schema_id: 作用域（限定的 schema id；NULL=全局）。
- visibility: 可见范围。global=管理员全局发布（人人可见可被召回）；personal=个人。
- is_pinned: 常驻上下文开关（仅 global 条目可置 1）；置 1 的全局条目无条件注入所有对话 prompt。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.timezone import now_beijing
from models.base import MainBase


class KnowledgeItem(MainBase):
    """知识库条目表"""
    __tablename__ = 'knowledge_items'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='创建者用户ID')
    title = Column(String(200), comment='知识标题')
    content = Column(Text, comment='自由文本知识内容（向后兼容；typed 条目可作人类可读摘要）')
    knowledge_type = Column(String(50), default='note',
                           comment='知识类型: note/terminology/calculation/relation/value_domain/convention/entity_map/sample_qa/quality')
    aliases = Column(Text, comment='别名/同义词(JSON 数组)，用于召回增强')
    payload = Column(Text, comment='结构化内容(JSON)，按 knowledge_type 解释，平台只透传')
    scope_schema_id = Column(Integer, nullable=True, index=True, comment='作用域：限定的 schema id；NULL=全局')
    visibility = Column(String(20), default='personal',
                        comment='可见范围: global=管理员全局发布(人人可见)/personal=个人')
    is_pinned = Column(Integer, default=0,
                       comment='常驻上下文开关(1/0)；仅 global 条目可置 1，置 1 无条件注入所有对话')
    is_active = Column(Integer, default=1, comment='启用状态(1/0，0=软删除)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


class KnowledgeVersion(MainBase):
    """知识条目版本快照 — create/update/delete/restore 全部追加一条，支持误删恢复"""
    __tablename__ = 'knowledge_versions'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    item_id = Column(Integer, nullable=False, index=True, comment='知识条目 id')
    version_no = Column(Integer, nullable=False, comment='条目内版本序号(1,2,3...)，与 item_id 联合唯一')
    action = Column(String(20), nullable=False, comment='动作: create/update/delete/restore')
    snapshot = Column(Text, nullable=False, comment='条目全字段 JSON 快照（含 is_active）')
    operator_id = Column(Integer, comment='操作人用户ID')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
