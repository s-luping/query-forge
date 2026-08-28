# -*- coding: UTF-8 -*-
"""
多轮对话 SQL 生成器

第一轮走完整召回流水线（委托 core.retrieval.SchemaRetriever），
后续轮次直接复用对话历史 + 首轮已确定的 schema 上下文。
"""
from typing import Optional, List

from app.logger import logger
from app.timezone import now_beijing
from core.llm_client import LLMClient
from core.gen_sql import SqlGenerator
from core.gen_audit import write_query_audit_log
from core.ret_keywords import KeywordExtractor
from core.ret_retriever import SchemaRetriever


def _parse_tables_from_csv(schema_csv: str) -> List[str]:
    """从 schema CSV 解析表名（第一列，跳过表头行）

    跨库模式下表名带库前缀（库名.表名），一并返回（追问轮用于表关系匹配）。
    """
    tables: List[str] = []
    for line in (schema_csv or '').split('\n'):
        line = line.strip()
        if not line or line.startswith('表名'):
            continue
        t = line.split(',')[0].strip()
        if t and t not in tables:
            tables.append(t)
    return tables


class ChatSession:
    """对话 SQL 生成器"""

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator,
                 user: dict = None):
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()
        self.retriever = SchemaRetriever(user=user, user_id=user_id)
        self.user = user or {'user_id': user_id, 'role': 'user'}

    # ---------- 链路日志（与 pipeline 对齐，供审计查看） ----------

    def _log_step(self, steps: list, step_name: str, data: dict):
        steps.append({
            "step": step_name,
            "timestamp": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        })

    # ---------- 消息处理 ----------

    def process_first_message(
        self,
        query: str,
        schema_name: Optional[str] = None,
        db_type: str = "sqlite",
        knowledge_content: str = "",
        scope_schema_id: Optional[int] = None,
        pre_log: Optional[list] = None
    ) -> dict:
        """第一轮消息：走完整流水线（关键词→字段召回→表聚合→LLM生成）

        Args:
            pre_log: 路由层前置步骤（鉴权/模型/知识库），追加到链路头部

        Returns:
            {"sql": ..., "is_valid": ..., "schema_csv": ..., "messages": [...], "audit_log_id": ...}
        """
        import json
        start_time = now_beijing()
        pipeline_log = list(pre_log) if pre_log else []
        self._log_step(pipeline_log, "PIPELINE_START", {
            "user_id": self.user_id, "query": query,
            "schema_name": schema_name or "全部",
        })

        # Step 1: 关键词提取
        keywords = self.keyword_extractor.extract(query, top_k=10)
        self._log_step(pipeline_log, "STEP1_KEYWORDS", {
            "query": query, "keywords": keywords, "count": len(keywords)})

        # Step 2: 字段召回（向量优先，DB 降级；向量编码用原始 query 语义）
        recalled_fields = self.retriever.recall_fields(keywords, schema_name, query=query)
        self._log_step(pipeline_log, "STEP2_RECALL", {
            "method": "vector" if self.retriever.vector_loaded else "database_query",
            "keywords": keywords, "recalled_count": len(recalled_fields),
            "recalled_fields": [{"schema": f.get("schema_name") or '',
                                 "table": f.get("table_name"), "column": f.get("column_name")}
                                for f in recalled_fields[:10]]})

        # Step 3: 按表聚合，获取完整表结构
        aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
        self._log_step(pipeline_log, "STEP3_AGGREGATE", {
            "recalled_table_count": len(aggregation.get('tables', [])),
            "tables": aggregation.get('tables', []),
            "total_field_count": len(aggregation.get('all_fields', {}))})

        # Step 3.5: 权限裁剪统计（库级 / 表级 / 字段级）
        self._log_permission_stats(pipeline_log, aggregation, schema_name)

        # 概念级召回：typed 知识单独召回 + relation 动态扩表
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        recall = self.retriever.recall_knowledge(query, scope_schema_id=scope_id)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "matched_count": len(recall['items']),
            "related_tables": recall['related_tables']})
        if recall['related_tables']:
            aggregation = self.retriever.extend_aggregation_with_tables(
                aggregation, recall['related_tables'], schema_name)
            self._log_step(pipeline_log, "STEP_EXTEND_TABLES", {
                "tables": aggregation.get('tables', []),
                "total_field_count": len(aggregation.get('all_fields', {}))})

        # 构建 schema CSV（会保存到对话上下文，供后续轮次复用）
        schema_csv = SchemaRetriever.build_schema_csv(aggregation)

        # 人工维护的表关系 → JOIN 提示（随 schema 上下文一并注入）
        relations_text = self.retriever.get_relations_text(aggregation.get('tables', []))

        logger.info(f"[ChatSession] 第一轮 - schema 上下文已构建，字段数: {len(aggregation.get('all_fields', {}))}")

        # Step 4: 构建 messages 数组（召回的知识文本并入【领域知识】）
        kb = knowledge_content or ""
        if recall['prompt_text']:
            kb = (kb + "\n\n" + recall['prompt_text']).strip() if kb else recall['prompt_text']
        system_prompt = self._build_system_prompt(schema_csv, db_type, kb, relations_text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        self._log_step(pipeline_log, "STEP4_CONTEXT", {
            "has_knowledge": bool(knowledge_content),
            "schema_csv_lines": len(schema_csv.split('\n'))})

        # Step 4.5: 可否生成 SQL 判断 — 信息不足则提前返回，引导用户补充
        judge_prompt = self.sql_generator.judge_generatable_prompt(
            query=query, schema_csv=schema_csv,
            knowledge_content=kb, relations_text=relations_text)
        self._log_step(pipeline_log, "STEP_JUDGE_PROMPT", {
            "prompt_length": len(judge_prompt)})
        try:
            judge = self.llm_client.call_llm_json(judge_prompt)
        except Exception as e:
            self._log_step(pipeline_log, "STEP_JUDGE_ERROR", {"error": str(e)})
            judge = None
        self._log_step(pipeline_log, "STEP_JUDGE_RESULT", {
            "can_generate": (judge or {}).get('can_generate'),
            "reason": (judge or {}).get('reason', ''),
            "missing_info": (judge or {}).get('missing_info', []),
            "suggestion": (judge or {}).get('suggestion', '')})
        if judge and not judge.get('can_generate', True):
            duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
            jt = judge.get('_judge_tokens') or {}
            audit_log_id = write_query_audit_log(
                self.user_id, self.user, query, '', '',
                gateway_result=None, duration_ms=duration_ms,
                pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str))
            return {
                "sql": '', "is_valid": False,
                "error_message": judge.get('suggestion') or '信息不足，请补充后重试',
                "columns": None, "schema_csv": schema_csv,
                "tables": aggregation.get('tables', []), "keywords": keywords,
                "messages": messages, "duration_ms": duration_ms,
                "raw_response": '', "gateway": None, "pipeline_log": pipeline_log,
                "need_more_info": True,
                "missing_info": judge.get('missing_info', []),
                "suggestion": judge.get('suggestion', ''),
                "judge_reason": judge.get('reason', ''),
                "audit_log_id": audit_log_id,
                "tokens": {
                    "prompt_tokens": jt.get('prompt_tokens', 0),
                    "completion_tokens": jt.get('completion_tokens', 0),
                    "total_tokens": jt.get('total_tokens', 0),
                },
            }

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)
        self._log_step(pipeline_log, "STEP5_RESULT", {
            "sql": llm_result.get('sql', ''),
            "total_tokens": llm_result.get("total_tokens", 0)})

        # Step 6-7: 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        generated_sql = sql
        sql, is_valid, error_msg, gateway_info = self._apply_gateway(
            sql, is_valid, error_msg, db_type, schema_name)
        self._log_step(pipeline_log, "STEP6_VALIDATE", {
            "is_valid": is_valid, "error_message": error_msg,
            "columns": columns[:10] if columns else None})
        if gateway_info:
            self._log_step(pipeline_log, "STEP7_GATEWAY", {
                "is_allowed": gateway_info.get("is_allowed"),
                "block_reason": gateway_info.get("block_reason"),
                "was_modified": gateway_info.get("was_modified"),
                "tables": gateway_info.get("tables", []),
                "hit_sensitive": gateway_info.get("hit_sensitive", False)})

        # Step 8: 审计日志
        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
        audit_log_id = write_query_audit_log(
            self.user_id, self.user, query, generated_sql, sql,
            gateway_result=gateway_info, duration_ms=duration_ms,
            pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str)
        )

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "schema_csv": schema_csv,
            "tables": aggregation.get('tables', []),
            "keywords": keywords,
            "messages": messages,
            "duration_ms": duration_ms,
            "raw_response": llm_result.get("raw_response", ""),
            "gateway": gateway_info,
            "pipeline_log": pipeline_log,
            "audit_log_id": audit_log_id,
            "tokens": {
                "prompt_tokens": llm_result.get("prompt_tokens", 0),
                "completion_tokens": llm_result.get("completion_tokens", 0),
                "total_tokens": llm_result.get("total_tokens", 0)
            }
        }

    def process_followup_message(
        self,
        conversation_messages: list,
        new_user_content: str,
        schema_csv: str,
        first_tables: Optional[List[str]] = None,
        db_type: str = "sqlite",
        schema_name: Optional[str] = None,
        knowledge_content: str = "",
        scope_schema_id: Optional[int] = None,
        pre_log: Optional[list] = None
    ) -> dict:
        """后续轮次消息：使用对话历史 + 已保存的 schema 上下文

        Args:
            conversation_messages: 数据库中已存储的消息（含 role/content/sql）
            new_user_content: 用户的新消息（修改意见）
            schema_csv: 第一轮保存的 schema CSV
            db_type: 数据库类型
            schema_name: 数据源/schema 名（用于追问召回追踪）
            knowledge_content: 创建对话时关联的知识库内容
            pre_log: 路由层前置步骤（鉴权/模型/知识库），追加到链路头部

        Returns:
            {"sql": ..., "is_valid": ..., "messages": [...], "audit_log_id": ...}
        """
        import json
        start_time = now_beijing()
        pipeline_log = list(pre_log) if pre_log else []
        self._log_step(pipeline_log, "PIPELINE_START", {
            "user_id": self.user_id, "query": new_user_content,
            "schema_name": schema_name or "复用上一轮", "mode": "followup",
        })

        # Step 1: 关键词提取（对追问重新提取，保证链路完整）
        keywords = self.keyword_extractor.extract(new_user_content, top_k=10)
        self._log_step(pipeline_log, "STEP1_KEYWORDS", {
            "query": new_user_content, "keywords": keywords,
            "count": len(keywords), "mode": "followup"})

        # Step 2-3: 针对新问题重新召回/聚合（仅链路追踪；失败降级不阻断主流程）
        try:
            recalled_fields = self.retriever.recall_fields(
                keywords, schema_name, query=new_user_content)
            self._log_step(pipeline_log, "STEP2_RECALL", {
                "method": "vector" if self.retriever.vector_loaded else "database_query",
                "keywords": keywords, "recalled_count": len(recalled_fields),
                "recalled_fields": [{"schema": f.get("schema_name") or '',
                                     "table": f.get("table_name"), "column": f.get("column_name")}
                                    for f in recalled_fields[:10]]})
            aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
            self._log_step(pipeline_log, "STEP3_AGGREGATE", {
                "recalled_table_count": len(aggregation.get('tables', [])),
                "tables": aggregation.get('tables', []),
                "total_field_count": len(aggregation.get('all_fields', {}))})
        except Exception as e:
            logger.warning(f"[ChatSession] 追问召回失败，降级复用上一轮上下文: {e}")
            self._log_step(pipeline_log, "STEP2_RECALL", {
                "method": "reuse_previous_context", "keywords": keywords,
                "recalled_count": 0, "recalled_fields": []})
            self._log_step(pipeline_log, "STEP3_AGGREGATE", {
                "reuse_schema_csv": True,
                "schema_csv_lines": len(schema_csv.split('\n'))})
            aggregation = None

        # 累积召回：首轮表集合(first_tables) ∪ 追问重召回表 ∪ 知识扩表
        # 仅当首轮表集合已知时重建（带权限裁剪），否则沿用 router 全量 schema_csv（向后兼容旧对话）
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        followup_recall = self.retriever.recall_knowledge(new_user_content, scope_schema_id=scope_id)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "matched_count": len(followup_recall['items']),
            "related_tables": followup_recall['related_tables']})

        relation_tables = None
        if first_tables:
            merged_tables = set(first_tables)
            if aggregation is not None:
                merged_tables |= set(aggregation.get('tables', []))
            merged_tables |= set(followup_recall['related_tables'])
            try:
                recalled = [{'table_name': t} for t in merged_tables]
                merged_aggregation = self.retriever.aggregate_tables(recalled, schema_name)
                schema_csv_used = SchemaRetriever.build_schema_csv(merged_aggregation)
                relation_tables = merged_aggregation.get('tables', [])
                self._log_step(pipeline_log, "STEP_CUMULATIVE_AGGREGATE", {
                    "merged_table_count": len(relation_tables),
                    "first_tables": len(first_tables),
                    "from_recall": len(aggregation.get('tables', [])) if aggregation else 0,
                    "from_knowledge": len(followup_recall['related_tables'])})
                # Step 3.5: 权限裁剪统计（累积后）
                self._log_permission_stats(pipeline_log, merged_aggregation, schema_name)
            except Exception as e:
                logger.warning(f"[ChatSession] 累积聚合失败，回退全量 schema_csv: {e}")
                schema_csv_used = schema_csv
                relation_tables = _parse_tables_from_csv(schema_csv)
        else:
            schema_csv_used = schema_csv
            relation_tables = _parse_tables_from_csv(schema_csv)

        messages = self._build_messages_from_history(
            conversation_messages, schema_csv_used, db_type, knowledge_content
        )

        # 概念级召回知识文本并入【领域知识】
        if followup_recall['prompt_text']:
            # 在现有 system prompt 末尾追加召回知识（复用已构建的 messages）
            if messages and messages[0].get('role') == 'system':
                extra = followup_recall['prompt_text']
                base = messages[0]['content']
                if extra not in base:
                    messages[0]['content'] = (base + "\n\n【领域知识(追问召回)】\n" + extra).strip()

        # 人工维护的表关系（基于累积/全量表集合）：追加 JOIN 提示
        if relation_tables:
            followup_relations = self.retriever.get_relations_text(relation_tables)
            if followup_relations and messages and messages[0].get('role') == 'system':
                base = messages[0]['content']
                if '【表关系（已人工确认的 JOIN 条件）】' not in base:
                    messages[0]['content'] = (
                        base + "\n\n【表关系（已人工确认的 JOIN 条件）】\n" + followup_relations.strip()
                        + "\n多表查询时必须优先使用上述连接条件，不要自行猜测连接字段。"
                    ).strip()

        # 追加新的 user 消息
        messages.append({"role": "user", "content": new_user_content})

        logger.info(f"[ChatSession] 跟进消息 - 历史轮次: {len(conversation_messages)}，总消息: {len(messages)}")

        # Step 4: 上下文
        self._log_step(pipeline_log, "STEP4_CONTEXT", {
            "has_knowledge": bool(knowledge_content),
            "history_rounds": len(conversation_messages),
            "schema_csv_lines": len(schema_csv.split('\n'))})

        # Step 4.5: 可否生成 SQL 判断 — 信息不足则提前返回，引导用户补充
        # 传入最近对话历史，让判断基于上下文（追问如「只保留某列」需结合上一轮表/字段）
        followup_relations_for_judge = ""
        if relation_tables:
            followup_relations_for_judge = self.retriever.get_relations_text(relation_tables)
        judge_prompt = self.sql_generator.judge_generatable_prompt(
            query=new_user_content, schema_csv=schema_csv_used,
            knowledge_content=knowledge_content,
            relations_text=followup_relations_for_judge,
            history_queries=conversation_messages)
        self._log_step(pipeline_log, "STEP_JUDGE_PROMPT", {
            "prompt_length": len(judge_prompt)})
        try:
            judge = self.llm_client.call_llm_json(judge_prompt)
        except Exception as e:
            self._log_step(pipeline_log, "STEP_JUDGE_ERROR", {"error": str(e)})
            judge = None
        self._log_step(pipeline_log, "STEP_JUDGE_RESULT", {
            "can_generate": (judge or {}).get('can_generate'),
            "reason": (judge or {}).get('reason', ''),
            "missing_info": (judge or {}).get('missing_info', []),
            "suggestion": (judge or {}).get('suggestion', '')})
        if judge and not judge.get('can_generate', True):
            duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
            jt = judge.get('_judge_tokens') or {}
            try:
                audit_log_id = write_query_audit_log(
                    self.user_id, self.user, new_user_content, '', '',
                    gateway_result=None, duration_ms=duration_ms,
                    pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str))
            except Exception:
                logger.warning("跟进判断不足审计日志写入失败（不影响主流程）")
                audit_log_id = None
            return {
                "sql": '', "is_valid": False,
                "error_message": judge.get('suggestion') or '信息不足，请补充后重试',
                "columns": None, "messages": messages, "duration_ms": duration_ms,
                "raw_response": '', "gateway": None, "pipeline_log": pipeline_log,
                "need_more_info": True,
                "missing_info": judge.get('missing_info', []),
                "suggestion": judge.get('suggestion', ''),
                "judge_reason": judge.get('reason', ''),
                "audit_log_id": audit_log_id,
                "tokens": {
                    "prompt_tokens": jt.get('prompt_tokens', 0),
                    "completion_tokens": jt.get('completion_tokens', 0),
                    "total_tokens": jt.get('total_tokens', 0),
                },
            }

        # Step 5: 调用 LLM
        llm_result = self.llm_client.chat(messages)
        self._log_step(pipeline_log, "STEP5_RESULT", {
            "sql": llm_result.get('sql', ''),
            "total_tokens": llm_result.get("total_tokens", 0)})

        # Step 6-7: 验证 + 权限网关
        sql = llm_result.get('sql', '')
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        generated_sql = sql
        sql, is_valid, error_msg, gateway_info = self._apply_gateway(
            sql, is_valid, error_msg, db_type, schema_name)
        self._log_step(pipeline_log, "STEP6_VALIDATE", {
            "is_valid": is_valid, "error_message": error_msg,
            "columns": columns[:10] if columns else None})
        if gateway_info:
            self._log_step(pipeline_log, "STEP7_GATEWAY", {
                "is_allowed": gateway_info.get("is_allowed"),
                "block_reason": gateway_info.get("block_reason"),
                "was_modified": gateway_info.get("was_modified"),
                "tables": gateway_info.get("tables", []),
                "hit_sensitive": gateway_info.get("hit_sensitive", False)})

        # Step 8: 审计日志（与首轮一致：完整链路 问题→关键词→召回→生成）
        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
        try:
            audit_log_id = write_query_audit_log(
                self.user_id, self.user, new_user_content, generated_sql, sql,
                gateway_result=gateway_info, duration_ms=duration_ms,
                pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str))
        except Exception:
            logger.warning("跟进消息审计日志写入失败（不影响主流程）")
            audit_log_id = None

        return {
            "sql": sql,
            "is_valid": is_valid,
            "error_message": error_msg,
            "columns": columns,
            "messages": messages,
            "duration_ms": duration_ms,
            "raw_response": llm_result.get("raw_response", ""),
            "gateway": gateway_info,
            "pipeline_log": pipeline_log,
            "audit_log_id": audit_log_id,
            "tokens": {
                "prompt_tokens": llm_result.get("prompt_tokens", 0),
                "completion_tokens": llm_result.get("completion_tokens", 0),
                "total_tokens": llm_result.get("total_tokens", 0)
            }
        }

    # ---------- 内部方法 ----------

    def _log_permission_stats(self, pipeline_log: list, aggregation: dict,
                              schema_name: Optional[str]):
        """记录权限裁剪统计：库级可见性 / 表级白名单 / 字段级访问分布"""
        from collections import Counter
        from app.permissions import (get_visible_schema_ids, get_table_grants_by_schema,
                                     get_column_access_map)
        try:
            visible = get_visible_schema_ids(self.user)
            table_grants = get_table_grants_by_schema(self.user)
            tables = aggregation.get('tables', [])
            col_map = (get_column_access_map(self.user, schema_name=schema_name,
                                             table_names=tables or None)
                       if tables else {})
            dist = Counter(col_map.values())
            self._log_step(pipeline_log, "STEP_PERMISSION", {
                "schema_visible": ("全部" if visible is None
                                   else (f"{len(visible)} 个" if visible else "无")),
                "table_grant_schemas": len(table_grants),
                "fields_in_context": len(aggregation.get('all_fields', {})),
                "field_access": {
                    "SELECT": dist.get('SELECT', 0),
                    "FILTER": dist.get('FILTER', 0),
                    "NONE": dist.get('NONE', 0),
                },
            })
        except Exception as e:
            self._log_step(pipeline_log, "STEP_PERMISSION_ERROR", {"error": str(e)})

    def _apply_gateway(self, sql: str, is_valid: bool, error_msg: Optional[str],
                       db_type: str, schema_name: Optional[str] = None):
        """SQL 权限网关：拦截 / 改写；失败不阻断主流程

        Returns:
            (sql, is_valid, error_msg, gateway_info)
        """
        if not is_valid:
            return sql, is_valid, error_msg, None
        try:
            from services.sql_gateway import SqlGateway
            gw = SqlGateway(self.user)
            gw_result = gw.process(sql, schema_name=schema_name, db_type=db_type)
            if not gw_result.is_allowed:
                is_valid = False
                error_msg = gw_result.block_reason
            elif gw_result.was_modified:
                sql = gw_result.sql
            return sql, is_valid, error_msg, gw_result.to_dict()
        except Exception as e:
            logger.warning(f"[ChatSession] 网关处理失败: {e}")
            return sql, is_valid, error_msg, None

    def _build_system_prompt(self, schema_csv: str, db_type: str,
                             knowledge_content: str = "",
                             relations_text: str = "") -> str:
        """构建 system prompt"""
        db_name = db_type.upper() if db_type else "SQLite"
        prompt = f"""你是一个专业的SQL生成助手。请根据用户的自然语言查询和表结构，生成正确的{db_name}查询语句。

【表结构】
{schema_csv}

【规则】
1. 只生成SELECT查询语句，不要包含INSERT、UPDATE、DELETE等操作
2. 确保所有列名和表名都在提供的表结构中存在
3. 如果需要连接多个表，请使用适当的JOIN
4. 添加适当的WHERE条件来过滤数据
5. 如果用户提出修改意见，请基于上一轮的SQL进行修改优化
6. 维度层级过滤（极其重要）：数据采用父子层级存储，父节点值=子节点汇总（预聚合）。【领域知识】中列出的每一个维度列都必须添加 WHERE 条件，用户未指定时使用最高级父节点（根节点），不要混用不同层级。遗漏任何一个维度列都会导致数据翻倍"""

        if knowledge_content:
            prompt += f"\n\n【领域知识】\n{knowledge_content}"

        if relations_text:
            prompt += ("\n\n【表关系（已人工确认的 JOIN 条件）】\n" + relations_text.strip()
                       + "\n多表查询时必须优先使用上述连接条件，不要自行猜测连接字段。")

        prompt += "\n\n只返回SQL语句，不要包含其他解释文字。"
        return prompt

    def _build_messages_from_history(
        self,
        conversation_messages: list,
        schema_csv: str,
        db_type: str = "sqlite",
        knowledge_content: str = ""
    ) -> list:
        """将数据库消息历史转换为 LLM messages 数组"""
        messages = [
            {"role": "system", "content": self._build_system_prompt(schema_csv, db_type, knowledge_content)}
        ]

        for msg in conversation_messages:
            # 兼容 dict（router 传入）与 ORM 对象两种形态
            role = msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', None)
            content = msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', '')
            sql = msg.get('sql') if isinstance(msg, dict) else getattr(msg, 'sql', None)
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                # 助理消息使用提取的 SQL 作为 content
                assistant_content = sql or content
                messages.append({"role": "assistant", "content": assistant_content})

        return messages
