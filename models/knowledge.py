"""知识库模型 — 表名 knowledge_items

字段语义：
- content: 自由文本知识（业务口径/表关系/计算规则等），向后兼容，生成 SQL 时注入提示词。
           对 typed 条目可留空或作为人类可读摘要。
- knowledge_type: 知识类型（平台不解释具体值，仅做路由/渲染）。
   内置类型：note(普通笔记/自由文本) / terminology(术语别名) / calculation(计算规则)
            / relation(表关系) / value_domain(取值域) / convention(约定)
            / entity_map(实体映射) / sample_qa(样例问答)
- aliases: 同义词/别名 JSON 数组字符串，用于召回增强（命中别名即召回该条目）。
- payload: 结构化内容 JSON 字符串，按 knowledge_type 解释，平台只透传 + 内建类型渲染。
- scope_schema_id: 作用域（限定的 schema id；NULL=全局）。relation 类型忽略此限制（关系天然跨库）。
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from models.base import MainBase
from app.timezone import now_beijing


class KnowledgeItem(MainBase):
    """知识库条目表"""
    __tablename__ = 'knowledge_items'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='创建者用户ID')
    title = Column(String(200), comment='知识标题')
    content = Column(Text, comment='自由文本知识内容（向后兼容；typed 条目可作人类可读摘要）')
    knowledge_type = Column(String(50), default='note',
                           comment='知识类型: note/terminology/calculation/relation/value_domain/convention/entity_map/sample_qa')
    aliases = Column(Text, comment='别名/同义词(JSON 数组)，用于召回增强')
    payload = Column(Text, comment='结构化内容(JSON)，按 knowledge_type 解释，平台只透传')
    scope_schema_id = Column(Integer, nullable=True, index=True, comment='作用域：限定的 schema id；NULL=全局')
    is_active = Column(Integer, default=1, comment='启用状态(1/0，0=软删除)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')
