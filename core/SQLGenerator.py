import re
from typing import List, Optional, Tuple, Dict, Any


class SqlGenerator:
    """SQL生成器类"""

    DB_TYPE_QUOTES = {
        "mysql": "`",
        "sqlite": "",
        "postgresql": '"',
        "oracle": "",
        "sqlserver": ""
    }

    def __init__(self):
        pass

    def _get_quote(self, db_type: str) -> str:
        """获取指定数据库类型的引用符"""
        return self.DB_TYPE_QUOTES.get(db_type.lower(), "")

    def _quote_identifier(self, identifier: str, db_type: str) -> str:
        """为标识符添加引号"""
        quote = self._get_quote(db_type)
        if quote:
            return f"{quote}{identifier}{quote}"
        return identifier

    def generate_sql_prompt(
        self,
        query: str,
        schema_csv: str = "",
        sample_values: str = "",
        table_relations: str = "",
        history_queries: List[Dict[str, str]] = None,
        domain_knowledge: str = "",
        db_type: str = "sqlite"
    ) -> str:
        """生成用于大模型的SQL生成提示

        Args:
            query: 用户查询
            schema_csv: 表结构CSV内容（从数据库动态获取）
            sample_values: 字段示例值文本
            table_relations: 表间关系文本
            history_queries: 历史成功查询 [{query, sql}]
            domain_knowledge: 领域知识内容
            db_type: 数据库类型 (mysql, sqlite, postgresql, oracle, sqlserver)
        """
        quote = self._get_quote(db_type)
        pre_rules = (
            "1. 只生成SELECT查询语句，不要包含INSERT、UPDATE、DELETE等操作\n"
            f"2. 使用{repr(quote) if quote else '无'}引用符包围表名和列名\n"
            "3. 如果需要连接多个表，请使用适当的JOIN\n"
            "4. 添加适当的WHERE条件来过滤数据\n"
            "5. 只返回SQL语句，不要包含其他解释文字\n"
            "6. 确保所有列名和表名都在提供的表结构中存在\n"
        )

        sample_values_section = ""
        if sample_values:
            sample_values_section = f"以下是一些字段的常见值，请在WHERE条件中使用这些值：\n{sample_values}\n"

        table_relations_section = ""
        if table_relations:
            table_relations_section = f"以下是表之间的关联关系，可用于JOIN操作：\n{table_relations}\n"

        history_section = ""
        if history_queries:
            history_section = "以下是类似的历史查询，可参考其SQL写法：\n"
            for i, h in enumerate(history_queries[:3]):
                history_section += f"{i+1}. Q: {h['query']}\n   A: {h['sql'][:200]}...\n\n"

        domain_section = ""
        if domain_knowledge:
            domain_section = f"{domain_knowledge}"

        db_name = db_type.upper() if db_type else "MySQL"
        prompt = (
            f"你是一个专业的SQL生成助手。请根据用户的自然语言查询、表结构(csv)、领域知识和规则，生成正确的{db_name}查询语句。\n"
            f"【用户问题】\n{query}"
            f"【表结构(csv)】\n{schema_csv}\n"
            f"【字段示例值】\n{sample_values_section}"
            f"【表间关系】\n{table_relations_section}"
            f"【领域知识】\n{domain_section}"
            f"【历史成功查询参考】\n{history_section}"
            f"【前置限制】\n{pre_rules}"
            "\n请严格按照上述要求生成SQL语句，只返回SQL语句，不要包含其他解释文字："
        )
        return prompt

    def validate_sql(self, sql: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
        """验证SQL语句的基本安全性"""
        sql_lower = sql.lower().strip()

        if not sql_lower.startswith('select') and not sql_lower.startswith('with'):
            return False, "只允许SELECT或WITH查询语句", sql_lower

        dangerous_keywords = ['drop', 'delete', 'update',
                              'insert', 'alter', 'create', 'truncate']
        for keyword in dangerous_keywords:
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, sql_lower):
                return False, f"不允许使用 '{keyword}' 关键字", None

        if re.search(r"(--|#|/\*|\*/)", sql):
            return False, "检测到潜在的SQL注入风险", None

        select_match = re.search(
            r"select\s+(.*?)\s+from", sql_lower, re.IGNORECASE | re.DOTALL)
        if select_match:
            columns_str = select_match.group(1)
            if columns_str.strip() == '*':
                columns = ['*']
            else:
                columns = [col.strip()
                           for col in columns_str.split(',') if col.strip()]
        else:
            columns = None

        return True, None, columns
