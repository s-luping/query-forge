# d:\projects\py\query-forge\test_pipeline.py
"""
测试11步SQL生成流程
"""
from app.logger import logger
from core.SQLGenerator import SqlGenerator
from core.LLMClient import LLMClient
from core.SQLPipeline import SQLPipeline
from core.VectorIndexBuilder import VectorIndexBuilder
from core.VectorStore import FieldVectorStore, MetricVectorStore, ValueVectorStore
from core.KeywordExtractor import KeywordExtractor
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_keyword_extraction():
    """测试关键词抽取"""
    logger.info("=" * 80)
    logger.info("测试关键词抽取")
    logger.info("=" * 80)

    extractor = KeywordExtractor()

    test_queries = [
        "查询用户表中所有年龄大于18岁的用户信息",
        "统计订单表中每个用户的订单数量",
        "找出销售额最高的前10个商品",
        "显示员工表中工资大于5000的员工姓名和部门"
    ]

    for query in test_queries:
        keywords = extractor.extract(query, top_k=5)
        logger.info(f"查询: {query}")
        logger.info(f"关键词: {keywords}")
        logger.info("-" * 40)


def test_vector_store():
    """测试向量存储"""
    logger.info("=" * 80)
    logger.info("测试向量存储")
    logger.info("=" * 80)

    import numpy as np

    field_store = FieldVectorStore()

    test_fields = [
        ("user_id", "用户ID", "users", "int"),
        ("username", "用户名", "users", "varchar"),
        ("age", "年龄", "users", "int"),
        ("order_id", "订单ID", "orders", "int"),
        ("amount", "订单金额", "orders", "decimal")
    ]

    for field_name, description, table_name, column_type in test_fields:
        vector = np.random.rand(768).astype('float32')
        field_store.add_field(field_name, description,
                              table_name, column_type, vector)

    logger.info(f"添加了 {len(test_fields)} 个字段到向量存储")

    test_query = "查询用户年龄"
    query_vector = np.random.rand(768).astype('float32')
    results = field_store.search(query_vector, top_k=3)

    logger.info(f"搜索 '{test_query}' 的结果:")
    for doc, metadata, score in results:
        logger.info(f"  - {doc} (分数: {score:.4f})")


def test_vector_index_builder():
    """测试向量索引构建"""
    logger.info("=" * 80)
    logger.info("测试向量索引构建")
    logger.info("=" * 80)

    user_id = 1
    schema_name = "test_schema"

    builder = VectorIndexBuilder(user_id)

    builder.build_indexes(schema_name)

    info = builder.get_index_info(schema_name)
    logger.info(f"索引信息: {info}")


def test_sql_pipeline():
    """测试SQL生成流程"""
    logger.info("=" * 80)
    logger.info("测试SQL生成流程")
    logger.info("=" * 80)

    user_id = 1
    query = "查询用户表中所有年龄大于18岁的用户信息"
    schema_name = "test_schema"

    llm_client = LLMClient(provider='glm', api_key='test_key')
    sql_generator = SqlGenerator()

    pipeline = SQLPipeline(user_id, llm_client, sql_generator)

    try:
        result = pipeline.run_pipeline(
            query=query,
            schema_name=schema_name,
            domain_knowledge="",
            history_queries=[],
            db_type="sqlite"
        )

        logger.info(f"查询: {query}")
        logger.info(f"关键词: {result['keywords']}")
        logger.info(f"召回字段数: {len(result['recalled_fields'])}")
        logger.info(f"召回指标数: {len(result['recalled_metrics'])}")
        logger.info(f"召回值数: {len(result['recalled_values'])}")
        logger.info(f"生成的SQL: {result['sql']}")
        logger.info(f"SQL验证: {'通过' if result['is_valid'] else '失败'}")
        if result['error_message']:
            logger.info(f"错误信息: {result['error_message']}")

    except Exception as e:
        logger.error(f"SQL生成流程测试失败: {e}")


def test_complete_workflow():
    """测试完整工作流程"""
    logger.info("=" * 80)
    logger.info("测试完整工作流程")
    logger.info("=" * 80)

    try:
        test_keyword_extraction()
        test_vector_store()
        test_vector_index_builder()
        test_sql_pipeline()

        logger.info("=" * 80)
        logger.info("所有测试完成！")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_complete_workflow()
