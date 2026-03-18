# -*- coding: UTF-8 -*-
"""
向量索引测试脚本
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.VectorStore import FieldVectorStore, MetricVectorStore, ValueVectorStore
from core.SQLPipeline import SQLPipeline
import numpy as np


def test_vector_index(user_id: int, schema_name: str = None):
    """测试向量索引"""
    print(f"\n{'='*60}")
    print(f"测试向量索引 - 用户: {user_id}, Schema: {schema_name}")
    print('='*60)

    vector_dir = os.path.join('db', 'vectors', f'user_{user_id}')

    if schema_name:
        field_path = os.path.join(vector_dir, f'{schema_name}_fields.pkl')
        metric_path = os.path.join(vector_dir, f'{schema_name}_metrics.pkl')
        value_path = os.path.join(vector_dir, f'{schema_name}_values.pkl')
    else:
        field_path = os.path.join(vector_dir, 'fields.pkl')
        metric_path = os.path.join(vector_dir, 'metrics.pkl')
        value_path = os.path.join(vector_dir, 'values.pkl')

    print(f"\n索引文件路径:")
    print(f"  字段: {field_path}")
    print(f"  指标: {metric_path}")
    print(f"  值: {value_path}")

    if not os.path.exists(field_path):
        print(f"\n错误: 字段索引文件不存在!")
        return

    field_store = FieldVectorStore()
    field_store.load(field_path)

    print(f"\n字段索引信息:")
    print(f"  向量数量: {len(field_store.metadata)}")
    print(f"  文档数量: {len(field_store.documents)}")

    print(f"\n前10个字段:")
    for i, (doc, meta) in enumerate(zip(field_store.documents[:10], field_store.metadata[:10])):
        print(f"  {i+1}. {meta.get('table_name')}.{meta.get('field_name')} - {meta.get('description', '')[:30]}")

    test_keywords = ['采购', '订单', '用户', '金额', '商品']

    print(f"\n{'='*60}")
    print("测试关键词搜索")
    print('='*60)

    pipeline = SQLPipeline(user_id=user_id, llm_client=None, sql_generator=None)

    for keyword in test_keywords:
        print(f"\n关键词: {keyword}")

        query_vector = pipeline._get_embedding(keyword)
        results = field_store.search(query_vector, top_k=5)

        print(f"  召回结果 (top 5):")
        for doc, meta, score in results:
            table = meta.get('table_name', '')
            field = meta.get('field_name', '')
            desc = meta.get('description', '')[:30]
            print(f"    - {table}.{field}: {desc} (score: {score:.4f})")

    print(f"\n{'='*60}")
    print("测试关键词验证")
    print('='*60)

    keywords = ['采购', '次数', '商家', '金额']
    keyword_set = set(k.lower() for k in keywords)

    print(f"\n关键词: {keywords}")

    relevant_count = 0
    for keyword in keywords:
        query_vector = pipeline._get_embedding(keyword)
        results = field_store.search(query_vector, top_k=10)

        for doc, meta, score in results:
            table_name = (meta.get('table_name') or '').lower()
            field_name = (meta.get('field_name') or '').lower()
            description = (meta.get('description') or '').lower()

            is_relevant = any(
                kw in table_name or kw in field_name or kw in description
                for kw in keyword_set
            )

            if is_relevant:
                relevant_count += 1
                print(f"  相关: {meta.get('table_name')}.{meta.get('field_name')}")

    print(f"\n相关字段数: {relevant_count}")

    if relevant_count == 0:
        print("\n警告: 向量召回结果完全不相关，需要回退到数据库查询!")


def test_db_recall(user_id: int, schema_name: str = None):
    """测试数据库召回"""
    print(f"\n{'='*60}")
    print("测试数据库关键词召回")
    print('='*60)

    pipeline = SQLPipeline(user_id=user_id, llm_client=None, sql_generator=None)

    keywords = ['采购', '次数', '商家', '金额']
    print(f"\n关键词: {keywords}")

    fields = pipeline._recall_field_info_from_db(keywords, schema_name)

    print(f"\n召回字段数: {len(fields)}")

    tables = set(f.get('table_name') for f in fields)
    print(f"召回表: {tables}")

    print(f"\n字段列表:")
    for f in fields[:20]:
        print(f"  - {f.get('table_name')}.{f.get('field_name')}: {f.get('description', '')[:30]}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='测试向量索引')
    parser.add_argument('--user_id', type=int, default=1, help='用户ID')
    parser.add_argument('--schema', type=str, default='pjmall', help='Schema名称')
    args = parser.parse_args()

    test_vector_index(args.user_id, args.schema)
    test_db_recall(args.user_id, args.schema)
