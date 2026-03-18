# -*- coding: UTF-8 -*-
"""
测试单个问题的向量索引结果
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.VectorStore import FieldVectorStore
from core.SQLPipeline import SQLPipeline


def test_query(user_id: int, schema_name: str, query: str):
    """测试单个查询的向量索引结果"""
    print(f"\n问题: {query}")
    print('='*60)

    vector_dir = os.path.join('db', 'vectors', f'user_{user_id}')
    field_path = os.path.join(vector_dir, f'{schema_name}_fields.pkl')

    if not os.path.exists(field_path):
        print(f"错误: 索引文件不存在 - {field_path}")
        return

    field_store = FieldVectorStore()
    field_store.load(field_path)

    pipeline = SQLPipeline(user_id=user_id, llm_client=None, sql_generator=None)

    keywords = pipeline.step1_extract_keywords(query)
    print(f"关键词: {keywords}")

    keyword_set = set(k.lower() for k in keywords)

    print(f"\n向量召回结果:")
    all_results = []
    for keyword in keywords:
        query_vector = pipeline._get_embedding(keyword)
        results = field_store.search(query_vector, top_k=10)
        for doc, meta, score in results:
            key = f"{meta.get('table_name')}.{meta.get('field_name')}"
            if key not in [r[0] for r in all_results]:
                all_results.append((key, meta, score))

    relevant_results = []
    for key, meta, score in all_results:
        table_name = (meta.get('table_name') or '').lower()
        field_name = (meta.get('field_name') or '').lower()
        description = (meta.get('description') or '').lower()

        is_relevant = any(
            kw in table_name or kw in field_name or kw in description
            for kw in keyword_set
        )

        if is_relevant:
            relevant_results.append((key, meta, score))
            print(f"  ✓ {key}: {meta.get('description', '')[:40]}")
        else:
            print(f"  ✗ {key}: {meta.get('description', '')[:40]}")

    print(f"\n相关字段数: {len(relevant_results)}")

    if len(relevant_results) == 0:
        print("\n回退到数据库查询:")
        fields = pipeline._recall_field_info_from_db(keywords, schema_name)
        tables = set(f.get('table_name') for f in fields)
        print(f"  表: {tables}")
        for f in fields[:10]:
            print(f"  - {f.get('table_name')}.{f.get('field_name')}")


if __name__ == '__main__':
    test_query(
        user_id=1,
        schema_name='pjmall',
        query='查询采购次数最多的商家对其采购的金额是多少'
    )
