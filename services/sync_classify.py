# -*- coding: UTF-8 -*-
"""字段自动分类 — 基于命名规则推断敏感等级

分类规则（优先级从高到低）：
    confidential: password/passwd/pwd/secret/token/api_key/private_key
    confidential: ssn/idcard/id_card/identity/credential
    sensitive:    phone/mobile/tel/telephone/fax
    sensitive:    email/mail
    sensitive:    salary/income/wage/compensation
    sensitive:    address/addr/location
    sensitive:    birthday/birth/age/gender
    internal:      status/state/type/level/category/code
    public:       其余所有字段
"""
import re

# 规则列表：(正则模式, 敏感等级) — 按优先级排序
_RULES = [
    # confidential — 不可见
    (r'password|passwd|pwd|secret|token|api_?key|private_?key|credential', 'confidential'),
    (r'ssn|id_?card|idcard|identity|national_?id', 'confidential'),

    # sensitive — 可用不可见
    (r'phone|mobile|tel(ephone)?|fax', 'sensitive'),
    (r'email|e_?mail', 'sensitive'),
    (r'salary|income|wage|compensation|bonus|commission', 'sensitive'),
    (r'address|addr|location|street|zip_?code|postal', 'sensitive'),
    (r'birth(day|date)?|^age$|gender|sex', 'sensitive'),
    (r'passport|visa|license', 'sensitive'),
    (r'bank|account|card_?no|card_?number', 'sensitive'),

    # internal — 可读但内部
    (r'status|state|type|level|category|flag|is_\w+', 'internal'),
    (r'code|sort|order|seq|step', 'internal'),
]

_compiled_rules = [(re.compile(p, re.IGNORECASE), level) for p, level in _RULES]


def classify_column(column_name: str) -> str:
    """根据字段名推断敏感等级

    Returns: public / internal / sensitive / confidential
    """
    if not column_name:
        return 'public'

    name_lower = column_name.lower()
    for pattern, level in _compiled_rules:
        if pattern.search(name_lower):
            return level

    return 'public'


def classify_batch(column_names: list[str]) -> dict[str, str]:
    """批量分类，返回 {column_name: sensitive_level}"""
    return {name: classify_column(name) for name in column_names}
