# -*- coding: UTF-8 -*-
"""关键词抽取 - jieba 分词 + 停用词过滤 + TF 统计"""
import os
import re
from collections import Counter
from typing import List, Set

import jieba

from app.logger import logger

# 优先使用项目本地字典，避免 pip 包缺少 dict.txt 导致分词失败
# core/ret_keywords.py → 上溯 2 级到项目根（__file__ 位于 core/ 下）
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
        """加载停用词：唯一来源为 data/jieba/stop_words.txt（每行一个词，# 开头为注释）"""
        stop_words: Set[str] = set()
        stop_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'jieba', 'stop_words.txt')
        if not os.path.exists(stop_file):
            logger.warning(f"停用词文件不存在: {stop_file}，停用词过滤将不生效")
            return stop_words
        with open(stop_file, 'r', encoding='utf-8') as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith('#'):
                    stop_words.add(word)
        logger.info(f"已加载停用词文件 {stop_file}，共 {len(stop_words)} 个停用词")
        return stop_words

    def _load_custom_words(self):
        """加载自定义词库：唯一来源为 data/jieba/custom_words.txt（每行一个词，# 开头为注释）"""
        custom_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'jieba', 'custom_words.txt')
        if not os.path.exists(custom_file):
            logger.warning(f"自定义词库文件不存在: {custom_file}，跳过加载")
            return
        count = 0
        with open(custom_file, 'r', encoding='utf-8') as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith('#'):
                    jieba.add_word(word)
                    count += 1
        logger.info(f"已加载自定义词库 {custom_file}，共 {count} 个自定义词")

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

        # 停用词匹配忽略大小写（英文问句 "Show/the" 与词表小写条目对齐）
        if word.lower() in self.stop_words:
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
