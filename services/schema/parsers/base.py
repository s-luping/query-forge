# -*- coding: UTF-8 -*-
"""解析器共享异常与工具"""


class DDLParseError(Exception):
    """DDL 解析错误"""
    pass


def extract_table_spans(ddl: str, create_pattern: str):
    """按 CREATE TABLE 匹配切分每张表的 DDL 片段

    返回 [(table_ddl, next_match_start)] 列表，供方言解析器逐表处理。
    """
    import re
    matches = list(re.finditer(create_pattern, ddl, re.IGNORECASE))
    spans = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ddl)
        spans.append(ddl[start:end])
    return spans


def check_duplicate_tables(ddl: str, create_pattern: str, group: int = 1, normalize=None):
    """检测 DDL 中的重复表名，重复则抛出 DDLParseError"""
    import re
    names = []
    for m in re.finditer(create_pattern, ddl, re.IGNORECASE):
        name = m.group(group)
        if normalize:
            name = normalize(name)
        if name in names:
            raise DDLParseError(f"表名重复：{name}")
        names.append(name)
    return names
