# d:\projects\py\query-forge\core\KeywordExtractor.py
import os
import re
import jieba
from typing import List, Set
from collections import Counter
from app.logger import logger

# 优先使用项目本地字典，避免 pip 包缺少 dict.txt 导致分词失败
_LOCAL_DICT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'jieba', 'dict.txt')
if os.path.exists(_LOCAL_DICT):
    jieba.set_dictionary(_LOCAL_DICT)


class KeywordExtractor:
    """关键词抽取类 - 使用jieba进行中文分词和关键词提取"""

    def __init__(self):
        """初始化关键词抽取器"""
        self.stop_words = self._load_stop_words()
        self._load_custom_words()

    def _load_stop_words(self) -> Set[str]:
        """加载停用词"""
        stop_words = {
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
            '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
            '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '些',
            '吗', '啊', '吧', '呢', '哦', '嗯', '呀', '啦', '呗', '嘛',
            '查询', '显示', '列出', '统计', '计算', '获取', '找出', '返回',
            '想要', '需要', '希望', '请', '帮我', '帮我查', '帮我找',
            '数据', '信息', '记录', '内容', '详情', '情况', '状态',
            '所有', '全部', '每个', '各个', '所有', '整个', '总共',
            '多少', '几个', '几', '数量', '个数', '总数', '合计',
            '什么', '哪些', '哪个', '如何', '怎样', '怎么', '为什么'
        }
        return stop_words

    def _load_custom_words(self):
        """加载自定义词库"""
        custom_words = [
            '用户', '订单', '商品', '金额', '数量', '时间', '日期', '状态',
            '姓名', '年龄', '性别', '地址', '电话', '邮箱', '身份证',
            '部门', '职位', '工资', '入职', '离职', '请假', '加班',
            '销售额', '利润', '成本', '库存', '采购', '供应商', '客户',
            '登录', '注册', '支付', '退款', '发货', '收货', '评价',
            '浏览', '点击', '收藏', '购买', '加入购物车', '下单',
            '完成', '取消', '待处理', '处理中', '已发货', '已收货',
            '创建时间', '更新时间', '删除时间', '操作时间',
            '主键', '外键', '索引', '唯一', '非空', '默认值',
            '平均值', '最大值', '最小值', '总和', '计数', '分组',
            '排序', '升序', '降序', '限制', '偏移', '分页'
        ]
        for word in custom_words:
            jieba.add_word(word)

    def extract(self, text: str, top_k: int = 10) -> List[str]:
        """
        从文本中抽取关键词
        :param text: 输入文本
        :param top_k: 返回前k个关键词
        :return: 关键词列表
        """
        if not text:
            return []

        text = text.strip()
        keywords = []

        words = jieba.cut(text)
        word_freq = Counter()

        for word in words:
            word = word.strip()
            if self._is_valid_keyword(word):
                word_freq[word] += 1

        for word, freq in word_freq.most_common(top_k):
            keywords.append(word)

        logger.debug(f"从文本 '{text[:50]}...' 中抽取关键词: {keywords}")
        return keywords

    def _is_valid_keyword(self, word: str) -> bool:
        """判断是否为有效的关键词"""
        if not word or len(word) < 2:
            return False

        if word in self.stop_words:
            return False

        if word.isdigit():
            return False

        if re.match(r'^[^\w\u4e00-\u9fa5]+$', word):
            return False

        return True

    def extract_with_weights(self, text: str, top_k: int = 10) -> List[tuple]:
        """
        从文本中抽取带权重的关键词
        :param text: 输入文本
        :param top_k: 返回前k个关键词
        :return: 带权重的关键词列表 [(keyword, weight), ...]
        """
        if not text:
            return []

        text = text.strip()
        keywords_with_weights = []

        words = jieba.cut(text)
        word_freq = Counter()

        for word in words:
            word = word.strip()
            if self._is_valid_keyword(word):
                word_freq[word] += 1

        total = sum(word_freq.values())
        if total > 0:
            for word, freq in word_freq.most_common(top_k):
                weight = freq / total
                keywords_with_weights.append((word, weight))

        logger.debug(
            f"从文本 '{text[:50]}...' 中抽取带权重关键词: {keywords_with_weights}")
        return keywords_with_weights

    def extract_from_query(self, query: str) -> dict:
        """
        从查询中提取结构化信息
        :param query: 用户查询
        :return: 包含关键词、表名、字段名等的字典
        """
        result = {
            'keywords': [],
            'table_names': [],
            'field_names': [],
            'values': [],
            'aggregations': [],
            'conditions': []
        }

        keywords = self.extract(query, top_k=20)
        result['keywords'] = keywords

        aggregation_keywords = ['总数', '数量', '个数', '平均', '最大', '最小', '总和', '合计']
        for keyword in keywords:
            if any(agg in keyword for agg in aggregation_keywords):
                result['aggregations'].append(keyword)

        condition_keywords = ['等于', '大于', '小于', '包含', '不等于', '在', '是']
        for keyword in keywords:
            if any(cond in keyword for cond in condition_keywords):
                result['conditions'].append(keyword)

        logger.debug(f"从查询 '{query[:50]}...' 中提取结构化信息: {result}")
        return result
