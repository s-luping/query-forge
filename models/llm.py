"""LLM 数据模型 — 配置和调用记录"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Boolean
from models import Base


class LLMConfig(Base):
    """LLM API配置表"""
    __tablename__ = 'llm_configs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    provider = Column(String(50), nullable=False, comment='模型供应商')
    model = Column(String(100), nullable=False, comment='模型名称')
    api_key = Column(Text, nullable=False, comment='API密钥')
    base_url = Column(String(500), comment='API地址')
    max_tokens = Column(Integer, default=8000, comment='最大Token数')
    temperature = Column(Float, default=0.2, comment='生成随机性')
    timeout = Column(Integer, default=300, comment='请求超时(秒)')
    is_default = Column(Boolean, default=False, comment='是否默认')
    is_active = Column(Boolean, default=True, comment='是否启用')
    description = Column(Text, comment='备注')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class LLMLog(Base):
    """LLM调用记录表"""
    __tablename__ = 'llm_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='所属用户')
    conversation_id = Column(Integer, nullable=True, index=True, comment='关联对话ID')
    provider = Column(String(50), default='', comment='模型供应商')
    question = Column(Text, nullable=False, comment='用户问题')
    model = Column(String(100), nullable=False, comment='模型名称')
    conditions = Column(Text, comment='查询条件')
    result = Column(Text, comment='生成结果')
    duration_ms = Column(Float, comment='耗时(毫秒)')
    prompt_tokens = Column(Integer, default=0, comment='输入Token')
    completion_tokens = Column(Integer, default=0, comment='输出Token')
    total_tokens = Column(Integer, default=0, comment='总Token')
    cost = Column(Float, default=0.0, comment='调用成本')
    status = Column(String(20), default='success', comment='状态(success/warning/error)')
    error_message = Column(Text, comment='错误信息')
    created_at = Column(DateTime, default=datetime.now, index=True, comment='创建时间')
