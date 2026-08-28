import re
from typing import List, Optional, Tuple, Dict


class SqlGenerator:
    """SQL生成器类"""

    DB_TYPE_QUOTES = {
        "mysql": "`",
        "sqlite": "",
        "postgresql": '"',
        "oracle": "",
        "sqlserver": ""
    }

    def _get_quote(self, db_type: str) -> str:
        """获取指定数据库类型的引用符"""
        return self.DB_TYPE_QUOTES.get(db_type.lower(), "")

    def generate_sql_prompt(
            self,
            query: str,
            schema_csv: str = "",
            knowledge_content: str = "",
            history_queries: List[Dict[str, str]] = None,
            db_type: str = "sqlite",
            relations_text: str = ""
    ) -> str:
        """生成用于大模型的SQL生成提示

        Args:
            query: 用户查询文本
            schema_csv: 表结构（从数据库动态获取）
            knowledge_content: 知识库内容（业务口径/表关系/计算规则等）
            history_queries: 历史成功查询 [{query, sql}]
            db_type: 数据库类型 (mysql, sqlite, postgresql, oracle, sqlserver)
            relations_text: 人工维护的表间 JOIN 关系提示（每行一条）
        """
        quote = self._get_quote(db_type)
        pre_rules = (
            "1. 只生成SELECT查询语句，不要包含INSERT、UPDATE、DELETE等操作\n"
            f"2. 使用{repr(quote) if quote else '无'}引用符包围表名和列名\n"
            "3. 如果需要连接多个表，请使用适当的JOIN,连接字段类型一般情况要保持一致\n"
            "4. 添加适当的WHERE条件来过滤数据\n"
            "5. 确保所有列名和表名都在提供的表结构中存在\n"
            "6. 禁止使用 SELECT *，必须显式列出需要查询的字段（避免敏感字段泄露）\n"
        )

        history_section = ""
        if history_queries:
            history_section = "以下是类似的历史查询，可参考其SQL写法：\n"
            for i, h in enumerate(history_queries[:3]):
                history_section += f"{i + 1}. Q: {h['query']}\n   A: {h['sql'][:200]}...\n\n"

        db_name = db_type.upper() if db_type else "MySQL"
        prompt_parts = [
            f"你是一个专业的SQL生成助手。请根据用户的自然语言查询、表结构(csv)、领域知识和规则，生成正确的{db_name}查询语句。",
            f"【用户问题】\n{query}",
            f"【表结构】\n{schema_csv}",
        ]

        if knowledge_content:
            prompt_parts.append(f"【领域知识】\n{knowledge_content.strip()}")
        if relations_text:
            prompt_parts.append(
                "【表关系（已人工确认的 JOIN 条件）】\n" + relations_text.strip()
                + "\n多表查询时必须优先使用上述连接条件，不要自行猜测连接字段。")
        if history_section:
            prompt_parts.append(f"【历史成功查询参考】\n{history_section}")

        prompt_parts.append(f"【前置限制】\n{pre_rules}")
        prompt_parts.append("请严格按照上述要求生成SQL语句，只返回SQL语句，不要包含其他解释文字：")

        prompt = '\n\n'.join(prompt_parts)
        return prompt

    def judge_generatable_prompt(
            self,
            query: str,
            schema_csv: str = "",
            knowledge_content: str = "",
            relations_text: str = "",
            history_queries: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """生成「可否生成 SQL」的判断提示词

        让 LLM 基于已召回的表结构 + 领域知识，判断用户问题信息是否充足。
        若不足，指出缺失项并给出补充建议，供前端引导用户补充后再生成。

        Args:
            query: 用户原始问题
            schema_csv: 已召回的表结构（按权限裁剪后的 CSV）
            knowledge_content: 领域知识（业务口径/表关系/计算规则）
            relations_text: 人工维护的 JOIN 关系提示
            history_queries: 最近对话历史 [{role, content, sql}]（追问轮传入，
                让判断基于上下文而非孤立的追问文本）
        """
        prompt_parts = [
            "你是一个 SQL 生成可行性判断专家。请判断：基于已召回的表结构、领域知识和对话上下文，能否为用户的自然语言问题生成一条能正确回答该问题的 SQL 查询。",
            f"【用户问题】\n{query}",
            f"【已召回表结构】\n{schema_csv or '（无）'}",
        ]
        if history_queries:
            history_section = "以下是最近对话历史（用户问过什么、上一轮生成了什么 SQL），用于理解当前追问的上下文：\n"
            for h in history_queries[-6:]:
                role = h.get('role', '')
                content = h.get('content', '') or ''
                sql = h.get('sql', '') or ''
                if role == 'user':
                    history_section += f"用户: {content}\n"
                else:
                    history_section += f"助手: {sql or content}\n"
            prompt_parts.append(f"【对话历史】\n{history_section}")
        if knowledge_content:
            prompt_parts.append(f"【领域知识】\n{knowledge_content.strip()}")
        if relations_text:
            prompt_parts.append(
                "【表关系（已人工确认的 JOIN 条件）】\n" + relations_text.strip())

        prompt_parts.append(
            "【判断标准】\n"
            "1. 表覆盖：用户问题涉及的实体是否都能在已召回的表中找到对应表；若问题明显指向未召回的表 → 不足\n"
            "2. 字段覆盖：所需的查询字段、过滤字段、关联字段是否都存在；关键字段缺失 → 不足\n"
            "3. 过滤条件明确：用户是否给出了足够的过滤条件（如时间范围、具体维度值）；问题模糊导致结果不可预期 → 不足\n"
            "4. 聚合/计算清晰：是否清楚要查什么（计数/求和/明细/分组等）；意图不明 → 不足\n"
            "5. 追问语义：若当前问题是针对上一轮结果的修改/收窄（如“只保留某列”“加上时间过滤”），"
            "应结合【对话历史】判断——上一轮已明确的表/字段可直接沿用，不要因为没有重复提及就判为不足\n"
            "6. 若仅是措辞口语化但意图可推断，应判为充足，不要过度苛求"
        )
        prompt_parts.append(
            "【输出要求】\n"
            "只返回一个 JSON 对象，不要包含任何其他文字，不要用 markdown 代码块包裹：\n"
            '{"can_generate": true/false, "reason": "简述判断依据", '
            '"missing_info": ["缺失的具体信息1", "..."], '
            '"suggestion": "给用户的补充建议（如何描述才能生成）"}\n'
            "若信息充足，missing_info 返回空数组，suggestion 返回空字符串。"
        )
        return '\n\n'.join(prompt_parts)

    def validate_sql(self, sql: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
        """验证SQL语句的基本安全性"""
        sql_lower = sql.lower().strip()

        if not sql_lower.startswith('select') and not sql_lower.startswith('with'):
            return False, "只允许SELECT或WITH查询语句", None

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
