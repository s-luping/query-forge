# -*- coding: UTF-8 -*-
"""
SQL生成流程优化类 - 按照11步流程生成SQL
使用FAISS本地向量检索，不依赖在线API
"""
import os
import numpy as np
import hashlib
from typing import List, Dict, Optional, Tuple
from app.logger import logger
from core.KeywordExtractor import KeywordExtractor
from core.VectorStore import FieldVectorStore, MetricVectorStore, ValueVectorStore
from core.LLMClient import LLMClient
from core.SQLGenerator import SqlGenerator
from core.VectorIndexBuilder import VECTOR_INDEX_THRESHOLD
from models import SchemaSessionLocal
from models.schema import Schema


class SQLPipeline:
    """SQL生成流程优化类 - 使用FAISS本地向量"""

    def __init__(self, user_id: int, llm_client: LLMClient, sql_generator: SqlGenerator):
        """
        初始化SQL生成流程
        :param user_id: 用户ID
        :param llm_client: LLM客户端（用于生成SQL，需要联网）
        :param sql_generator: SQL生成器
        """
        self.user_id = user_id
        self.llm_client = llm_client
        self.sql_generator = sql_generator
        self.keyword_extractor = KeywordExtractor()

        from core.VectorIndexBuilder import _get_embedding_model, _embedding_dimension
        model = _get_embedding_model()
        if model == "hash":
            self.dimension = 1024
        else:
            self.dimension = _embedding_dimension

        self.field_store = None
        self.metric_store = None
        self.value_store = None
        self._vector_loaded = False
        self._use_vector_search = False

    @classmethod
    def from_llm_config(cls, user_id: int, llm_client: LLMClient,
                        sql_generator: SqlGenerator, llm_config: dict = None) -> 'SQLPipeline':
        """从LLM配置创建SQLPipeline"""
        return cls(user_id, llm_client, sql_generator)

    def _get_field_count(self, schema_name: Optional[str] = None) -> int:
        """获取字段数量"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            return query.count()
        finally:
            db.close()

    def _load_vector_stores(self, schema_name: Optional[str] = None):
        """加载向量存储"""
        self._vector_loaded = False
        self._use_vector_search = False

        vector_dir = os.path.join('db', 'vectors', f'user_{self.user_id}')

        if schema_name:
            field_path = os.path.join(vector_dir, f'{schema_name}_fields.pkl')
            metric_path = os.path.join(vector_dir, f'{schema_name}_metrics.pkl')
            value_path = os.path.join(vector_dir, f'{schema_name}_values.pkl')
        else:
            field_path = os.path.join(vector_dir, 'fields.pkl')
            metric_path = os.path.join(vector_dir, 'metrics.pkl')
            value_path = os.path.join(vector_dir, 'values.pkl')

        field_count = self._get_field_count(schema_name)

        if not os.path.exists(field_path):
            if field_count >= VECTOR_INDEX_THRESHOLD:
                logger.info(f"字段数量 {field_count} 超过阈值 {VECTOR_INDEX_THRESHOLD}，自动构建向量索引...")
                from core.VectorIndexBuilder import VectorIndexBuilder
                builder = VectorIndexBuilder(self.user_id)
                try:
                    build_result = builder.build_indexes(schema_name)
                    logger.info(f"向量索引构建完成: {build_result}")
                except Exception as e:
                    logger.warning(f"自动构建索引失败: {e}，将使用数据库查询")
            else:
                logger.info(f"字段数量 {field_count} 未达阈值 {VECTOR_INDEX_THRESHOLD}，使用数据库直接查询")
                return

        if not os.path.exists(field_path):
            logger.info("向量索引文件不存在，将使用数据库直接查询")
            return

        self.field_store = FieldVectorStore()
        self.metric_store = MetricVectorStore()
        self.value_store = ValueVectorStore()

        try:
            field_loaded = self.field_store.load(field_path)
            metric_loaded = self.metric_store.load(metric_path)
            value_loaded = self.value_store.load(value_path)

            if field_loaded and self.field_store.is_built:
                self._vector_loaded = True
                self._use_vector_search = True
                logger.info(f"向量索引加载成功（FAISS本地），将使用向量检索")
            else:
                logger.warning("向量索引加载失败或不完整，将使用数据库直接查询")

        except Exception as e:
            logger.warning(f"加载向量索引时出错: {e}，将使用数据库直接查询")
            self.field_store = None
            self.metric_store = None
            self.value_store = None

    def step1_extract_keywords(self, query: str) -> List[str]:
        """步骤1: 抽取关键词"""
        keywords = self.keyword_extractor.extract(query, top_k=10)
        logger.info(f"步骤1 - 抽取关键词: {keywords}")
        return keywords

    def step2_recall_field_info(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """步骤2: 召回字段信息"""
        if not self._use_vector_search or not self.field_store or not self.field_store.is_built:
            logger.info("使用数据库直接查询召回字段信息")
            return self._recall_field_info_from_db(keywords, schema_name)

        try:
            recalled_fields = []
            seen_keys = set()
            keyword_set = set(k.lower() for k in keywords)

            for keyword in keywords:
                query_vector = self._get_embedding(keyword)
                results = self.field_store.search(query_vector, top_k=10)

                for doc, metadata, score in results:
                    key = f"{metadata.get('table_name')}.{metadata.get('field_name')}"
                    if key not in seen_keys:
                        table_name = (metadata.get('table_name') or '').lower()
                        field_name = (metadata.get('field_name') or '').lower()
                        description = (metadata.get('description') or metadata.get('field_description') or '').lower()

                        is_relevant = any(
                            kw in table_name or kw in field_name or kw in description
                            for kw in keyword_set
                        )

                        if is_relevant:
                            seen_keys.add(key)
                            recalled_fields.append(metadata)

            if recalled_fields:
                logger.info(f"步骤2 - 向量召回字段信息: {len(recalled_fields)} 个字段")
                tables = set(f.get('table_name') for f in recalled_fields)
                logger.info(f"召回的表: {tables}")
                return recalled_fields
            else:
                logger.warning("向量召回结果为空或不相关，回退到数据库查询")
                return self._recall_field_info_from_db(keywords, schema_name)

        except Exception as e:
            logger.warning(f"向量召回失败: {e}，回退到数据库查询")
            return self._recall_field_info_from_db(keywords, schema_name)

    def step3_recall_metric_info(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """步骤3: 召回指标信息"""
        if not self._use_vector_search or not self.metric_store or not self.metric_store.is_built:
            logger.info("从字段信息中推断指标")
            return self._infer_metrics_from_fields(keywords, schema_name)

        try:
            recalled_metrics = []
            seen_keys = set()
            keyword_set = set(k.lower() for k in keywords)

            for keyword in keywords:
                query_vector = self._get_embedding(keyword)
                results = self.metric_store.search(query_vector, top_k=10)

                for doc, metadata, score in results:
                    key = f"{metadata.get('table_name')}.{metadata.get('metric_name')}"
                    if key not in seen_keys:
                        metric_name = (metadata.get('metric_name') or '').lower()
                        description = (metadata.get('description') or '').lower()

                        is_relevant = any(
                            kw in metric_name or kw in description
                            for kw in keyword_set
                        )

                        if is_relevant:
                            seen_keys.add(key)
                            recalled_metrics.append(metadata)

            if recalled_metrics:
                logger.info(f"步骤3 - 向量召回指标信息: {len(recalled_metrics)} 个指标")
                return recalled_metrics
            else:
                logger.info("向量召回指标为空或不相关，从字段推断")
                return self._infer_metrics_from_fields(keywords, schema_name)

        except Exception as e:
            logger.warning(f"指标向量召回失败: {e}，从字段推断")
            return self._infer_metrics_from_fields(keywords, schema_name)

    def step4_recall_field_values(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """步骤4: 召回字段值"""
        if not self._use_vector_search or not self.value_store or not self.value_store.is_built:
            logger.info("使用数据库查询召回字段值")
            return self._recall_field_values_from_db(keywords, schema_name)

        try:
            recalled_values = []
            seen_keys = set()

            for keyword in keywords:
                query_vector = self._get_embedding(keyword)
                results = self.value_store.search(query_vector, top_k=5)

                for doc, metadata, score in results:
                    key = f"{metadata.get('table_name')}.{metadata.get('field_name')}.{metadata.get('value')}"
                    if key not in seen_keys and score < 1.0:
                        seen_keys.add(key)
                        recalled_values.append(metadata)

            if recalled_values:
                logger.info(f"步骤4 - 向量召回字段值: {len(recalled_values)} 个值")
                return recalled_values
            else:
                logger.info("向量召回值为空，使用数据库查询")
                return self._recall_field_values_from_db(keywords, schema_name)

        except Exception as e:
            logger.warning(f"字段值向量召回失败: {e}，使用数据库查询")
            return self._recall_field_values_from_db(keywords, schema_name)

    def step5_merge_recall_info(self, fields: List[Dict], metrics: List[Dict],
                                values: List[Dict]) -> Dict:
        """步骤5: 合并召回信息"""
        merged_info = {
            'fields': fields,
            'metrics': metrics,
            'values': values,
            'tables': set(),
            'all_fields': {}
        }

        for field in fields:
            table_name = field.get('table_name')
            field_name = field.get('field_name')
            merged_info['tables'].add(table_name)
            merged_info['all_fields'][f"{table_name}.{field_name}"] = field

        for metric in metrics:
            table_name = metric.get('table_name')
            merged_info['tables'].add(table_name)

        for value in values:
            table_name = value.get('table_name')
            field_name = value.get('field_name')
            if table_name and field_name:
                merged_info['tables'].add(table_name)
                key = f"{table_name}.{field_name}"
                if key not in merged_info['all_fields']:
                    merged_info['all_fields'][key] = {
                        'table_name': table_name, 'field_name': field_name}
                merged_info['all_fields'][key]['sample_values'] = merged_info['all_fields'][key].get(
                    'sample_values', [])
                merged_info['all_fields'][key]['sample_values'].append(
                    value.get('value'))

        merged_info['tables'] = list(merged_info['tables'])
        logger.info(
            f"步骤5 - 合并召回信息: {len(merged_info['tables'])} 个表, {len(merged_info['all_fields'])} 个字段")
        return merged_info

    def step6_filter_metric_info(self, merged_info: Dict, keywords: List[str]) -> Dict:
        """步骤6: 筛选指标信息"""
        filtered_metrics = []
        keyword_set = set(keywords)

        for metric in merged_info['metrics']:
            metric_name = metric.get('metric_name', '').lower()
            metric_desc = metric.get('description', '').lower()

            if any(keyword.lower() in metric_name or keyword.lower() in metric_desc
                   for keyword in keyword_set):
                filtered_metrics.append(metric)

        merged_info['filtered_metrics'] = filtered_metrics
        logger.info(f"步骤6 - 筛选指标信息: {len(filtered_metrics)} 个相关指标")
        return merged_info

    def step7_filter_table_info(self, merged_info: Dict, keywords: List[str]) -> Dict:
        """步骤7: 筛选表信息"""
        filtered_tables = []
        keyword_set = set(k.lower() for k in keywords)

        for table in merged_info['tables']:
            table_lower = table.lower()
            if any(keyword in table_lower for keyword in keyword_set):
                filtered_tables.append(table)

        if not filtered_tables:
            logger.warning("没有找到相关表，将使用数据库直接查询")
            merged_info['filtered_tables'] = []
            merged_info['need_fallback'] = True
            return merged_info

        merged_info['filtered_tables'] = filtered_tables
        logger.info(f"步骤7 - 筛选表信息: {len(filtered_tables)} 个相关表: {filtered_tables}")
        return merged_info

    def step8_add_context_info(self, merged_info: Dict, query: str,
                               domain_knowledge: str = "",
                               history_queries: List[Dict] = None) -> Dict:
        """步骤8: 添加上下文信息"""
        context_info = {
            'query': query,
            'domain_knowledge': domain_knowledge,
            'history_queries': history_queries or []
        }

        extracted_info = self.keyword_extractor.extract_from_query(query)
        context_info.update(extracted_info)

        merged_info['context'] = context_info
        logger.info(f"步骤8 - 添加上下文信息")
        return merged_info

    def step9_generate_sql(self, merged_info: Dict, db_type: str = "sqlite") -> str:
        """步骤9: 生成SQL（调用LLM，需要联网）"""
        schema_csv = self._generate_schema_csv(merged_info)
        sample_values = self._generate_sample_values(merged_info)
        table_relations = self._generate_table_relations(merged_info)

        prompt = self.sql_generator.generate_sql_prompt(
            query=merged_info['context']['query'],
            schema_csv=schema_csv,
            sample_values=sample_values,
            table_relations=table_relations,
            history_queries=merged_info['context']['history_queries'],
            domain_knowledge=merged_info['context']['domain_knowledge'],
            db_type=db_type
        )

        result = self.llm_client.call_llm_with_details(prompt)
        generated_sql = result['sql']
        logger.info(f"步骤9 - 生成SQL: {generated_sql}")
        return generated_sql

    def step10_validate_sql(self, sql: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
        """步骤10: 验证SQL语句"""
        is_valid, error_msg, columns = self.sql_generator.validate_sql(sql)
        logger.info(
            f"步骤10 - 验证SQL: {'通过' if is_valid else '失败'} - {error_msg}")
        return is_valid, error_msg, columns

    def step11_execute_sql(self, sql: str, db_path: str) -> List[Dict]:
        """步骤11: 执行SQL语句"""
        from core.DatabaseManager import DatabaseManager
        db_manager = DatabaseManager(db_path)
        results = db_manager.execute_query(sql, max_results=100)
        logger.info(f"步骤11 - 执行SQL: 返回 {len(results)} 条结果")
        return results

    def run_pipeline(self, query: str, schema_name: Optional[str] = None,
                     domain_knowledge: str = "", history_queries: List[Dict] = None,
                     db_type: str = "sqlite", db_path: Optional[str] = None) -> Dict:
        """运行完整的11步流程"""
        logger.info(f"开始运行11步SQL生成流程，查询: {query}")

        self._load_vector_stores(schema_name)

        keywords = self.step1_extract_keywords(query)
        fields = self.step2_recall_field_info(keywords, schema_name)
        metrics = self.step3_recall_metric_info(keywords, schema_name)
        values = self.step4_recall_field_values(keywords, schema_name)
        merged_info = self.step5_merge_recall_info(fields, metrics, values)
        merged_info = self.step6_filter_metric_info(merged_info, keywords)
        merged_info = self.step7_filter_table_info(merged_info, keywords)

        if merged_info.get('need_fallback'):
            logger.info("向量召回结果不相关，回退到数据库直接查询")
            fields = self._recall_field_info_from_db(keywords, schema_name)
            merged_info = self.step5_merge_recall_info(fields, [], [])
            merged_info['filtered_tables'] = list(set(f.get('table_name') for f in fields))
            merged_info['all_fields'] = {f"{f.get('table_name')}.{f.get('field_name')}": f for f in fields}

        merged_info = self.step8_add_context_info(
            merged_info, query, domain_knowledge, history_queries)
        sql = self.step9_generate_sql(merged_info, db_type)
        is_valid, error_msg, columns = self.step10_validate_sql(sql)

        result = {
            'query': query,
            'keywords': keywords,
            'recalled_fields': fields,
            'recalled_metrics': metrics,
            'recalled_values': values,
            'merged_info': merged_info,
            'sql': sql,
            'is_valid': is_valid,
            'error_message': error_msg,
            'columns': columns,
            'used_vector_search': self._use_vector_search
        }

        if is_valid and db_path:
            try:
                execution_results = self.step11_execute_sql(sql, db_path)
                result['execution_results'] = execution_results
                result['execution_success'] = True
            except Exception as e:
                result['execution_error'] = str(e)
                result['execution_success'] = False

        logger.info(f"11步流程执行完成，使用向量检索: {self._use_vector_search}")
        return result

    def _get_embedding(self, text: str) -> np.ndarray:
        """获取文本的向量表示"""
        from core.VectorIndexBuilder import _get_embedding_model, _embedding_dimension

        if not text or not text.strip():
            return np.zeros(self.dimension, dtype='float32')

        model = _get_embedding_model()
        if model == "hash":
            return self._get_hash_embedding(text)

        try:
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.astype('float32')
        except Exception as e:
            logger.warning(f"Embedding 失败: {e}，使用 hash 算法")
            return self._get_hash_embedding(text)

    def _get_hash_embedding(self, text: str) -> np.ndarray:
        """使用 hash 算法生成向量（备用方案）"""
        text = text.strip().lower()
        vector = np.zeros(self.dimension, dtype='float32')

        words = text.split()
        for word in words:
            hash_val = int(hashlib.md5(word.encode()).hexdigest()[:8], 16)
            idx = hash_val % self.dimension
            weight = len(word) / 10.0
            vector[idx] += weight

        for i in range(self.dimension):
            hash_input = f"{text}_{i}".encode('utf-8')
            hash_val = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
            vector[i] += (hash_val % 1000) / 1000.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector.astype('float32')

    def _recall_field_info_from_db(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """从数据库召回字段信息（只返回与关键词相关的表）"""
        if not keywords:
            return []

        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()

            keyword_set = set(k.lower() for k in keywords)
            relevant_tables = set()

            for item in items:
                table_name = (item.table_name or '').lower()
                column_name = (item.column_name or '').lower()
                column_desc = (item.column_description or '').lower()

                for keyword in keyword_set:
                    if keyword in table_name or keyword in column_name or keyword in column_desc:
                        relevant_tables.add(item.table_name)
                        break

            fields = []
            for item in items:
                if item.table_name not in relevant_tables:
                    continue
                field_info = {
                    'field_name': item.column_name,
                    'table_name': item.table_name,
                    'column_type': item.column_type,
                    'description': item.column_description or ''
                }
                fields.append(field_info)
            return fields
        finally:
            db.close()

    def _recall_field_values_from_db(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """从数据库召回字段值"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()
            values = []
            for item in items:
                if item.sample_values:
                    sample_list = [
                        v.strip() for v in item.sample_values.split(',') if v.strip()]
                    for value in sample_list:
                        values.append({
                            'field_name': item.column_name,
                            'table_name': item.table_name,
                            'value': value
                        })
            return values
        finally:
            db.close()

    def _infer_metrics_from_fields(self, keywords: List[str], schema_name: Optional[str] = None) -> List[Dict]:
        """从字段信息推断指标"""
        fields = self._recall_field_info_from_db(keywords, schema_name)
        metrics = []

        metric_keywords = ['金额', '价格', '数量',
                           '计数', '总和', '平均', '最大', '最小', '总计',
                           'amount', 'price', 'count', 'sum', 'avg', 'total']
        for field in fields:
            field_name = field['field_name'].lower()
            field_desc = field['description'].lower()

            for metric_keyword in metric_keywords:
                if metric_keyword in field_name or metric_keyword in field_desc:
                    metrics.append({
                        'metric_name': field['field_name'],
                        'table_name': field['table_name'],
                        'description': field['description']
                    })
                    break

        return metrics

    def _generate_schema_csv(self, merged_info: Dict) -> str:
        """生成Schema CSV格式（只包含筛选后的表）"""
        lines = ['schema_name,table_name,column_name,column_type,column_description,table_comment,primary_key,foreign_key,is_nullable,default_value']

        filtered_tables = merged_info.get('filtered_tables', [])

        for field_key, field_info in merged_info['all_fields'].items():
            table_name = field_info.get('table_name', '')
            if filtered_tables and table_name not in filtered_tables:
                continue
            field_name = field_info.get('field_name', '')
            column_type = field_info.get('column_type', '')
            description = field_info.get('description', '')
            table_comment = field_info.get('table_comment', '')
            primary_key = field_info.get('primary_key', '')
            foreign_key = field_info.get('foreign_key', '')
            is_nullable = field_info.get('is_nullable', True)
            default_value = field_info.get('default_value', '')

            lines.append(','.join([
                '',
                table_name,
                field_name,
                column_type,
                description,
                table_comment,
                primary_key,
                foreign_key,
                'YES' if is_nullable else 'NO',
                default_value or ''
            ]))

        return '\n'.join(lines)

    def _generate_sample_values(self, merged_info: Dict) -> str:
        """生成字段示例值（只包含筛选后的表）"""
        sample_lines = []
        filtered_tables = merged_info.get('filtered_tables', [])

        for field_key, field_info in merged_info['all_fields'].items():
            table_name = field_info.get('table_name', '')
            if filtered_tables and table_name not in filtered_tables:
                continue
            field_name = field_info.get('field_name', '')
            sample_values = field_info.get('sample_values', [])

            if sample_values:
                sample_lines.append(
                    f"{table_name}.{field_name}: {', '.join(sample_values[:5])}")

        return '\n'.join(sample_lines)

    def _generate_table_relations(self, merged_info: Dict) -> str:
        """生成表间关系"""
        tables = merged_info.get('filtered_tables', [])
        if len(tables) < 2:
            return ""

        relations = []
        for i, table1 in enumerate(tables):
            for table2 in tables[i+1:]:
                relations.append(f"{table1} 和 {table2} 可能存在关联关系")

        return '\n'.join(relations)
