# -*- coding: UTF-8 -*-
"""
多轮对话 SQL 生成器

第一轮走完整召回流水线（委托 core.retrieval.SchemaRetriever），
后续轮次直接复用对话历史 + 首轮已确定的 schema 上下文。
"""
from typing import Dict, List, Optional

from app.logger import logger
from app.timezone import now_beijing
from core.gen_audit import write_query_audit_log
from core.gen_sql import SqlGenerator
from core.llm_client import LLMClient
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
        if t and t not in tables:            tables.append(t)
    return tables


def _extract_tables_from_sql(sql: str) -> List[str]:
    """从 SQL 提取 FROM/JOIN 引用的表名（去库前缀、去重、保留字表名正确处理）

    用于追问轮：历史 SQL 实际用到的表作为"必留表"，保证上下文收敛不膨胀。

    用 sqlglot 解析（mysql 方言）——保留字表名（如 order）、反引号引用的表、
    别名等都能正确处理；解析失败时正则兜底。注意：早期版本用关键字黑名单过滤
    伪匹配，误杀了名为 order 的保留字表（order 表永远进不了追问轮上下文）。
    """
    tables: List[str] = []
    if not sql:
        return tables
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, dialect='mysql')
        for t in tree.find_all(exp.Table):
            name = t.name
            if name and name not in tables:
                tables.append(name)
        if tables:
            return tables
    except Exception:
        pass
    # 正则兜底（仅匹配 FROM/JOIN 后的首个标识符，ORDER BY 等关键字不会误命中）
    import re
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+([A-Za-z0-9_\.`"]+)', sql, re.IGNORECASE):
        name = m.group(1).strip('`"[]')
        name = name.split('.')[-1]      # schema.table → table
        if name and name not in tables:
            tables.append(name)
    return tables


def _extract_columns_from_sql(sql: str, db_type: str = 'mysql') -> set:
    """从 SQL 提取 (表名, 列名) 引用集合（别名解析），用于追问轮字段级裁剪白名单

    返回 {(table_name, column_name), ...}；解析失败返回空集（调用方回退全量 CSV）。
    """
    cols: set = set()
    if not sql:
        return cols
    try:
        import sqlglot
        from sqlglot import exp
        _DIALECTS = {'mysql': 'mysql', 'mariadb': 'mysql', 'doris': 'mysql',
                     'postgresql': 'postgres', 'postgres': 'postgres',
                     'oracle': 'oracle', 'sqlserver': 'tsql', 'mssql': 'tsql',
                     'sqlite': 'sqlite'}
        tree = sqlglot.parse_one(sql, dialect=_DIALECTS.get((db_type or '').lower()))
        alias_map = {t.alias_or_name: t.name for t in tree.find_all(exp.Table)}
        for c in tree.find_all(exp.Column):
            t = c.table or ''
            if not t or not c.name:
                continue
            cols.add((alias_map.get(t, t), c.name))
    except Exception:
        pass
    return cols


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
                                 "table": f.get("table_name"), "column": f.get("column_name"),
                                 "sensitive_level": f.get("sensitive_level") or 'public'}
                                for f in recalled_fields]})

        # Step 3: 按表聚合，获取完整表结构
        aggregation = self.retriever.aggregate_tables(recalled_fields, schema_name)
        self._log_step(pipeline_log, "STEP3_AGGREGATE", {
            "recalled_table_count": len(aggregation.get('tables', [])),
            "tables": aggregation.get('tables', []),
            "total_field_count": len(aggregation.get('all_fields', {}))})

        # Step 3.5: 权限裁剪统计（库级 / 表级 / 字段级）
        self._log_permission_stats(pipeline_log, aggregation, schema_name)

        # 概念级召回：typed 知识单独召回 + relation 动态扩表（自动执行，与用户勾选知识库无关）
        # 排除已勾选知识库内容（content 精确去重），避免同一知识在【领域知识】中出现两次
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        kb_base = knowledge_content or ''
        kb_parts = {p.strip() for p in kb_base.split('\n\n') if p.strip()}
        recall = self.retriever.recall_knowledge(
            query, scope_schema_id=scope_id, exclude_contents=kb_parts or None)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "source": "auto_concept_recall",
            "note": "自动概念召回（对全部知识条目关键词匹配，无需勾选知识库）",
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
            return self._need_more_info_result(
                judge, query, messages, pipeline_log, start_time, aggregation,
                schema_csv=schema_csv, tables=aggregation.get('tables', []),
                keywords=keywords)

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
                "reasoning_tokens": llm_result.get("reasoning_tokens", 0),
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
        # 追问/修改指令（如"不对 条件不对"）可能不含实质业务词——停用词过滤后为空，
        # 此时全库向量召回必然跑偏（召回过百个无关字段），直接复用首轮表集合。
        aggregation = None
        recalled_fields: List = []
        if not keywords:
            self._log_step(pipeline_log, "STEP2_RECALL", {
                "method": "reuse_previous_context", "keywords": keywords,
                "recalled_count": 0, "recalled_fields": [],
                "reason": "追问无实质业务关键词，跳过向量召回，直接复用上一轮表集合"})
            self._log_step(pipeline_log, "STEP3_AGGREGATE", {
                "reuse_schema_csv": True,
                "schema_csv_lines": len(schema_csv.split('\n'))})
        else:
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
        # 知识扩表（entity_map 等 payload.related_tables 声明的事实表）并入 keep_first：
        # 否则首轮 10 张召回杂表占满 MAX_TABLES 名额时（无历史 SQL 时 keep_first=首轮表集合），
        # 知识确认相关的事实表会在裁剪环节被整体挤掉（conv8「24-09费用合计」事故）。
        scope_id = scope_schema_id if scope_schema_id is not None else self.retriever.resolve_scope_schema_id(schema_name)
        # 自动召回排除已勾选知识内容（content 精确去重，防同一知识重复出现）
        kb_base = knowledge_content or ''
        kb_parts = {p.strip() for p in kb_base.split('\n\n') if p.strip()}
        followup_recall = self.retriever.recall_knowledge(
            new_user_content, scope_schema_id=scope_id, exclude_contents=kb_parts or None)
        self._log_step(pipeline_log, "STEP_RECALL_KNOWLEDGE", {
            "source": "auto_concept_recall",
            "note": "自动概念召回（对全部知识条目关键词匹配，无需勾选知识库）",
            "matched_count": len(followup_recall['items']),
            "related_tables": followup_recall['related_tables']})

        relation_tables = None
        if first_tables or aggregation is not None:
            # 历史 SQL 实际用到的表 → 必留表（最高优先，保证上下文收敛）
            # 首轮表不再无条件全量继承：只有被历史 SQL 用过、或本轮召回到、
            # 或知识扩表命中的表才进入候选，避免 CSV 每轮膨胀（139→293 行问题）。
            used_tables: List[str] = []
            for msg in conversation_messages:
                sql = msg.get('sql') if isinstance(msg, dict) else getattr(msg, 'sql', None)
                if sql:
                    used_tables.extend(_extract_tables_from_sql(sql))
            used_tables = list(dict.fromkeys(used_tables))
            first_set = set(first_tables) if first_tables else set()
            keep_first = set(used_tables) or (first_set if first_tables else None)
            # 知识扩表并入保留集：与历史 SQL 表同级的"必留表"待遇
            if followup_recall['related_tables']:
                keep_first = (keep_first or set()) | set(followup_recall['related_tables'])

            # 合并表集合：历史已用表在前（顺序稳定，供同名列去重裁决），召回/知识扩表在后
            # 注意：aggregation 可能为 None——追问无实质业务关键词（跳过向量召回）
            # 或召回异常降级时复用上一轮 schema_csv，此时 first_tables 非空仍会进入
            # 本分支，必须做 None 防御（与下方 full_scope / from_recall 保持一致），
            # 否则 NoneType.get 直接 500（conv11「26年9月一级科目总金额」追问事故）
            recall_tables = (aggregation.get('tables') or []) if aggregation else []
            merged_order = list(used_tables)
            for t in recall_tables + list(followup_recall['related_tables']):
                if t not in merged_order:
                    merged_order.append(t)
            try:
                # 小库直通：本轮召回命中整库标记时，合并表集合同样整库注入
                full_scope = bool(aggregation and aggregation.get('full_scope'))
                # 知识扩表标记 recall_source='knowledge'：聚合权重高于 DB 子串兜底，
                # 语义上"知识确认相关"的表不应与噪声表同权竞争
                knowledge_table_set = set(followup_recall['related_tables'])
                recalled = []
                for t in merged_order:
                    item = {'table_name': t}
                    if t in knowledge_table_set:
                        item['recall_source'] = 'knowledge'
                    if full_scope:
                        item['full_scope'] = True
                    recalled.append(item)
                # keep_first：历史 SQL 用过的表完整保留，超限只裁剪新增召回表
                merged_aggregation = self.retriever.aggregate_tables(
                    recalled, schema_name, keep_first=keep_first)
                # 字段级裁剪：白名单 = 历史 SQL 引用列(保底) ∪ 本轮召回列(可裁剪)
                # 召回列裁剪：同名列跨表只保留首个（按 merged_order 顺序）+ 未引用表每表上限，
                # 消除 product_brand 多表重复、维度表整表灌入的问题（主外键由 CSV 自动补齐）
                required_cols: set = set()   # 历史 SQL 引用列：硬需求，绝不裁
                for msg in conversation_messages:
                    sql = msg.get('sql') if isinstance(msg, dict) else getattr(msg, 'sql', None)
                    if sql:
                        required_cols |= _extract_columns_from_sql(sql, db_type)
                recall_cols: List = []     # 本轮召回列（软信号）：保序（向量相似度降序），可去重/限幅
                _recall_seen: set = set()
                for f in recalled_fields:
                    t = f.get('table_name')
                    c = f.get('column_name') or f.get('field_name')
                    if t and c and (t, c) not in _recall_seen:
                        _recall_seen.add((t, c))
                        recall_cols.append((t, c))
                if full_scope:
                    # 小库直通：整库注入，不做字段级裁剪
                    field_whitelist = None
                else:
                    field_whitelist = required_cols | self._trim_recall_cols(
                        merged_aggregation, required_cols, recall_cols)
                    # 知识扩表的列全部保留（对齐首轮 extend_aggregation_with_tables
                    # 注入完整表结构的行为）：字段级白名单只认「历史 SQL 引用列 ∪ 本轮
                    # 召回列」，知识表没有召回列，会被裁到只剩主外键——度量列
                    # （如 ACTUAL_VALUE）丢失，判断步仍以「缺金额字段」误拦截
                    # （conv8 事故第三层：表进来了，列没了）。
                    if knowledge_table_set:
                        for _f in (merged_aggregation.get('all_fields')
                                   or {}).values():
                            if _f.get('table_name') in knowledge_table_set:
                                field_whitelist.add(
                                    (_f['table_name'],
                                     _f.get('column_name') or ''))
                schema_csv_used = SchemaRetriever.build_schema_csv(
                    merged_aggregation, field_whitelist or None)
                relation_tables = merged_aggregation.get('tables', [])
                self._log_step(pipeline_log, "STEP_CUMULATIVE_AGGREGATE", {
                    "merged_table_count": len(relation_tables),
                    "used_tables_from_sql": used_tables,
                    "from_history": len(used_tables),
                    "from_recall": len(aggregation.get('tables', [])) if aggregation else 0,
                    "from_knowledge": len(followup_recall['related_tables']),
                    "note": "首轮表不再全量继承，仅保留历史SQL用过的+本轮召回到的表"})
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
            "schema_csv_lines": len(schema_csv_used.split('\n')),
            "tables_in_context": len(relation_tables) if relation_tables else 0})

        # Step 4.5: 可否生成 SQL 判断 — 信息不足则提前返回，引导用户补充
        # 传入最近对话历史，让判断基于上下文（追问如「只保留某列」需结合上一轮表/字段）
        # 判断 prompt 必须并入自动召回的知识（与首轮 kb 构造保持一致）：
        # 此前追问轮只传用户勾选知识（未勾选时为空），entity_map 等口径知识
        # （费用→AA0003、公司汇总→EETotal、项目汇总→PJTotal）进不了判断步，
        # 判断步看不到口径映射，只能以"缺实采值/缺表"反复拦截（conv8 连续 5 轮误拦截）。
        followup_relations_for_judge = ""
        if relation_tables:
            followup_relations_for_judge = self.retriever.get_relations_text(relation_tables)
        judge_kb = knowledge_content or ''
        if followup_recall['prompt_text']:
            judge_kb = ((judge_kb + '\n\n' + followup_recall['prompt_text']).strip()
                        if judge_kb else followup_recall['prompt_text'])
        judge_prompt = self.sql_generator.judge_generatable_prompt(
            query=new_user_content, schema_csv=schema_csv_used,
            knowledge_content=judge_kb,
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
            return self._need_more_info_result(
                judge, new_user_content, messages, pipeline_log, start_time,
                aggregation)

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
                "reasoning_tokens": llm_result.get("reasoning_tokens", 0),
                "total_tokens": llm_result.get("total_tokens", 0)
            }
        }

    # ---------- 内部方法 ----------

    def _need_more_info_result(self, judge: dict, query_text: str,
                               messages: list, pipeline_log: list,
                               start_time, aggregation: Optional[dict],
                               schema_csv: Optional[str] = None,
                               tables: Optional[List[str]] = None,
                               keywords: Optional[List[str]] = None) -> dict:
        """判断步拦截（need_more_info）结果构造 — 首轮/追问共用

        含权限归因提示（权限裁剪可能是"信息不足"的真实原因）与审计落库
        （失败不阻断主流程）。
        """
        import json
        duration_ms = int((now_beijing() - start_time).total_seconds() * 1000)
        perm_hint = self._permission_context_hint(aggregation)
        judge_msg = judge.get('suggestion') or '信息不足，请补充后重试'
        if perm_hint:
            judge_msg = f"{judge_msg}（{perm_hint}）"
        try:
            audit_log_id = write_query_audit_log(
                self.user_id, self.user, query_text, '', '',
                gateway_result=None, duration_ms=duration_ms,
                pipeline_log=json.dumps(pipeline_log, ensure_ascii=False, default=str))
        except Exception:
            logger.warning("判断不足审计日志写入失败（不影响主流程）")
            audit_log_id = None
        jt = judge.get('_judge_tokens') or {}
        result = {
            "sql": '', "is_valid": False,
            "error_message": judge_msg,
            "columns": None,
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
                "reasoning_tokens": jt.get('reasoning_tokens', 0),
                "total_tokens": jt.get('total_tokens', 0),
            },
        }
        if schema_csv is not None:
            result["schema_csv"] = schema_csv
        if tables is not None:
            result["tables"] = tables
        if keywords is not None:
            result["keywords"] = keywords
        return result

    def _permission_context_hint(self, aggregation: Optional[dict]) -> str:
        """生成用户可见的权限归因提示（用于「信息不足」场景）。

        背景：召回阶段按库/表/字段三级权限静默裁剪，LLM 只能看到用户有权限的
        表结构——当问题涉及的表/字段无权限时，判断步会报「信息不足」，但用户
        无法区分是表述不清还是权限不够。此提示把权限因素显式告知用户。

        Returns:
            空字符串 = 权限与信息不足无关（正常表述类问题），不追加提示。
        """
        try:
            from app.permissions import (
                get_column_access_map,
                get_visible_schema_ids,
                is_admin,
            )
            visible = get_visible_schema_ids(self.user)
            if visible == []:
                return ('当前账号未被授予任何数据访问权限（库/表授权为空），'
                        '请联系管理员配置角色授权后再试')
            tables = (aggregation.get('tables') or []) if aggregation else []
            if not tables:
                if visible is not None:
                    return ('未在您有权限的数据库中检索到与问题相关的表/字段：'
                            '可能是问题涉及的表无访问权限，或该库元数据尚未同步，'
                            '请联系管理员确认权限与数据同步状态')
                return ''
            if is_admin(self.user):
                return ''
            # 字段级 NONE 比例：受限字段已从上下文剔除，可能正是"缺信息"的来源
            col_map = get_column_access_map(
                self.user,
                schema_name=aggregation.get('schema_name') if aggregation else None,
                table_names=tables or None)
            if col_map:
                none_n = sum(1 for v in col_map.values() if v == 'NONE')
                if none_n:
                    return (f'注意：当前范围内有 {none_n} 个字段因权限受限'
                            f'未纳入本次分析，可能与信息不足有关')
        except Exception:
            pass
        return ''

    def _log_permission_stats(self, pipeline_log: list, aggregation: dict,
                              schema_name: Optional[str]):
        """记录权限裁剪统计：库级可见性 / 表级白名单 / 字段级访问分布"""
        from collections import Counter

        from app.permissions import (
            get_column_access_map,
            get_table_grants_by_schema,
            get_visible_schema_ids,
        )
        try:
            visible = get_visible_schema_ids(self.user)
            table_grants = get_table_grants_by_schema(self.user)
            tables = aggregation.get('tables', [])
            col_map = (get_column_access_map(self.user, schema_name=schema_name,
                                             table_names=tables or None)
                       if tables else {})
            dist = Counter(col_map.values())
            # 按敏感级别列出字段名，便于审计核对敏感/机密字段是否被正确处理
            by_level: Dict[str, List[str]] = {'sensitive': [], 'confidential': [],
                                              'internal': [], 'public': []}
            for _key, f in (aggregation.get('all_fields') or {}).items():
                lv = f.get('sensitive_level') or 'public'
                if lv in by_level:
                    by_level[lv].append(f"{f.get('table_name')}.{f.get('column_name')}")
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
                "sensitive_fields": by_level['sensitive'],
                "confidential_fields": by_level['confidential'],
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
            # 安全边界 fail-closed：网关异常（解析失败/权限查询故障等）时拦截本次查询，
            # 而非放行未校验的 SQL（此前 fail-open 会让该请求跳过全部权限校验）
            logger.warning(f"[ChatSession] 网关处理失败，已拦截: {e}")
            return sql, False, '权限网关处理异常，本次查询已拦截，请重试或联系管理员', None

    def _build_system_prompt(self, schema_csv: str, db_type: str,
                             knowledge_content: str = "",
                             relations_text: str = "") -> str:
        """构建 system prompt"""
        db_name = db_type.upper() if db_type else "SQLite"
        prompt = f"""你是一个专业的SQL生成助手。请根据用户的自然语言查询和表结构，生成正确的{db_name}查询语句。

【表结构】
{schema_csv}

【规则】
1. 仅生成SELECT；禁INSERT/UPDATE/DELETE等写操作
2. 列名/表名必须在提供的表结构中
3. 多表连接用JOIN，连接字段类型保持一致
4. 添加适当WHERE过滤
5. 用户修改意见→基于上一轮SQL修改
6. 维度层级过滤(必守)：维度列必须加WHERE，用户未指定用最高级父节点(根节点)，勿混用层级，遗漏任何维度列数据会翻倍
7. 禁止SELECT *，必须显式列出查询字段(防敏感泄露)"""

        if knowledge_content:
            kb = knowledge_content.strip()
            # 调用方已带段标题（【全局规则】/【领域知识】…）时原样注入，否则补默认标题
            prompt += f"\n\n{kb}" if kb.startswith('【') else f"\n\n【领域知识】\n{kb}"

        if relations_text:
            prompt += ("\n\n【表关系（已人工确认的 JOIN 条件）】\n" + relations_text.strip()
                       + "\n多表查询时必须优先使用上述连接条件，不要自行猜测连接字段。")

        prompt += "\n\n只返回SQL语句，不要包含其他解释文字。"
        return prompt

    # 追问轮历史滑动窗口：保留首轮 + 最近 N 轮（user+assistant 成对计为一轮）
    _HISTORY_WINDOW = 5
    # 未在历史 SQL 中引用过的表，白名单最多保留的召回列数（PRI/FK 由 CSV 构建自动补齐）
    _RECALL_COLS_CAP = 4
    # 同名列跨表去重仅作用于长复合列名（product_brand 等语义化字段）；
    # status/name/id 等通用短名列各表语义不同，不去重（order.status ≠ brand.status）
    _COL_NAME_DEDUP_MIN_LEN = 8
    # 召回列中的审计/删除标记类字段直接裁掉（生成 SQL 用不上；
    # 若确实需要，会通过历史 SQL 引用进入 required 保底，不受此限制）
    _AUDIT_COLS = ('created_by', 'updated_by', 'created_at', 'updated_at',
                   'create_time', 'update_time', 'create_by', 'update_by',
                   'deleted', 'is_deleted', 'is_delete')

    @staticmethod
    def _trim_recall_cols(aggregation: dict, required_cols: set,
                          recall_cols: list) -> set:
        """裁剪召回列：去重 + 限幅，仅作用于"软信号"召回列，历史引用列不裁

        recall_cols 须保持召回相似度降序（优先保留更相关的字段）。

        规则：
        1. 同名列跨表只保留第一个出现（仅限长复合列名 ≥ _COL_NAME_DEDUP_MIN_LEN，
           如 product_brand；status/name/id 等通用短名列各表语义不同，不去重；
           按 aggregation 表顺序裁决归属，required 已占名的列召回列同名不再加）
        2. 未在历史 SQL 引用过的表，每表最多 _RECALL_COLS_CAP 个召回列——
           避免 brand 表 8 个字段整表灌入（created_by/updated_at 等审计字段被裁）
        3. 已引用表的召回列不设上限（新查询的维度列可能落在任意已用表上，如
           order_detail.product_brand 用于"区分品牌"的 GROUP BY）
        """
        if not recall_cols:
            return set()
        tables = aggregation.get('tables', [])
        used_tables = {_t for (_t, _c) in required_cols}
        min_len = ChatSession._COL_NAME_DEDUP_MIN_LEN
        seen_names = {c for (_t, c) in required_cols}
        kept: set = set()
        counts: dict = {}
        for table in tables:                       # 顺序稳定（merged_order），裁决同名列归属
            cap = None if table in used_tables else ChatSession._RECALL_COLS_CAP
            for t, c in recall_cols:               # 保持召回相似度顺序，先到先得
                if t != table:
                    continue
                if c in ChatSession._AUDIT_COLS:
                    continue                       # 审计/删除标记类字段，直接裁
                if len(c) >= min_len and c in seen_names:
                    continue                       # 长复合列名已被更早的表/required 占用
                if cap is not None and counts.get(table, 0) >= cap:
                    continue
                kept.add((t, c))
                seen_names.add(c)
                counts[table] = counts.get(table, 0) + 1
        return kept

    def _build_messages_from_history(
        self,
        conversation_messages: list,
        schema_csv: str,
        db_type: str = "sqlite",
        knowledge_content: str = ""
    ) -> list:
        """将数据库消息历史转换为 LLM messages 数组

        多轮压缩（仅发送层，存储层保留全部记录）：
        1. 连续相同 user 消息去重：同一问题重复提交（前端重试/用户重发）时
           只保留最后一轮（user+assistant），较早轮次撤回
        2. 滑动窗口：仅保留首轮 + 最近 N 轮，更早轮次裁剪
        """
        msgs = self._dedup_history(list(conversation_messages))
        total = len(msgs)
        keep = 2 * self._HISTORY_WINDOW  # 最近 N 轮（每条 user/assistant 各占 1 条）
        if total > keep + 2:             # 2 = 首轮 user + 首轮 assistant
            msgs = msgs[:2] + msgs[-keep:]

        messages = [
            {"role": "system", "content": self._build_system_prompt(schema_csv, db_type, knowledge_content)}
        ]

        for msg in msgs:
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

    @staticmethod
    def _dedup_history(msgs: list) -> list:
        """发送层去重：连续相同 user 消息只保留最后一轮（user+assistant 成对撤回）

        场景：同一问题被重复提交（前端重试/用户重发），DB 存了多条相同 user 消息，
        发送给 LLM 时只保留最新一轮，避免重复上下文与互相矛盾的多版本 SQL。
        仅对"内容完全相同的连续 user 消息"生效，不误伤有意重问。
        存储层记录不动，仅影响发送给 LLM 的消息数组。
        """
        result: list = []
        last_user = None
        for msg in msgs:
            role = msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', None)
            content = msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', '')
            if role == 'user':
                if content and content == last_user:
                    # 与上一条 user 相同：撤回上一轮（assistant + user）
                    while result:
                        last = result[-1]
                        r = last.get('role') if isinstance(last, dict) else getattr(last, 'role', None)
                        if r == 'user':
                            result.pop()
                            break
                        result.pop()
                last_user = content
            result.append(msg)
        return result
