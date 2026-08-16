# -*- coding: UTF-8 -*-
"""
LLM客户端 - 通用大模型API调用
"""
import time
from typing import Optional

import requests

from app.logger import llm_logger


class LLMClient:
    """通用大模型客户端"""

    def __init__(self, provider: str = '', api_key: str = "", model: str = "",
                 base_url: Optional[str] = None,
                 max_tokens: int = 8000, timeout: int = 300, temperature: float = 0.7):
        """
        初始化客户端
        :param provider: 模型供应商名称（自由输入，如 OpenAI、DeepSeek 等）
        :param api_key: API密钥
        :param model: 模型名称
        :param base_url: API地址
        :param max_tokens: 最大生成token数
        :param timeout: 请求超时时间（秒）
        :param temperature: 生成随机性 (0-2)
        """
        self.provider = provider or ''
        self.provider_name = provider or ''
        self.base_url = base_url or ''
        self.api_key = api_key or ''
        self.model = model or ''
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.temperature = temperature

    def _extract_sql(self, text: str) -> str:
        """从API响应文本中提取SQL（去除markdown代码块标记）"""
        text = text.strip()
        if "```sql" in text:
            start = text.find("```sql") + 6
        elif "```" in text:
            start = text.find("```") + 3
        else:
            return text

        end = text.find("```", start)
        if end == -1:
            end = len(text)
        return text[start:end].strip()

    def call_real_llm_api(self, prompt: str) -> str:
        """调用大模型API，返回SQL"""
        result = self.call_llm_with_details(prompt)
        return result['sql']

    def call_llm_with_details(self, prompt: str) -> dict:
        """调用大模型API，返回详细信息"""
        if not self.api_key:
            raise ValueError(f"未配置 {self.provider_name} API密钥，请设置环境变量或在前端配置")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        start_time = time.time()

        llm_logger.info(f"【请求模型】{self.provider_name} - {self.model}")
        llm_logger.info(f"【发送内容】\n{prompt}")

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
        except Exception as e:
            llm_logger.error(f"【网络请求异常】{e}")
            raise RuntimeError(f"调用 {self.provider_name} API网络请求失败: {e}") from e

        if response.status_code != 200:
            error_msg = f"API返回错误状态码: {response.status_code}, {response.text}"
            llm_logger.error(f"【API错误】{error_msg}")
            raise ValueError(error_msg)

        result = response.json()
        if 'choices' not in result or not result['choices']:
            error_msg = f"API响应缺少choices字段: {result}"
            llm_logger.error(f"【响应异常】{error_msg}")
            raise ValueError(error_msg)

        raw_sql = result['choices'][0]['message']['content'].strip()
        sql = self._extract_sql(raw_sql)

        elapsed_time = time.time() - start_time

        prompt_tokens = result.get('usage', {}).get('prompt_tokens', 0)
        completion_tokens = result.get('usage', {}).get('completion_tokens', 0)
        total_tokens = result.get('usage', {}).get('total_tokens', 0)

        llm_logger.info(f"【响应内容】\n{raw_sql}")
        llm_logger.info(f"【提取SQL】\n{sql}")
        llm_logger.info(f"【Token消耗】输入: {prompt_tokens}, 输出: {completion_tokens}, 总计: {total_tokens}")
        llm_logger.info(f"【耗时】{elapsed_time:.2f}秒")

        return {
            'sql': sql,
            'raw_response': raw_sql,
            'provider': self.provider,
            'model': self.model,
            'duration_ms': round(elapsed_time * 1000, 2),
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens
        }

    def chat(self, messages: list, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None) -> dict:
        """多轮对话调用 — 支持 messages 数组格式

        :param messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        :param max_tokens: 最大生成token数（不指定则用实例默认值）
        :param temperature: 生成随机性（不指定则用实例默认值）
        :return: {"sql": ..., "raw_response": ..., "tokens": ...}
        """
        if not self.api_key:
            raise ValueError(f"未配置 {self.provider_name} API密钥，请设置环境变量或在前端配置")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens
        }

        start_time = time.time()

        llm_logger.info(f"【多轮对话】{self.provider_name} - {self.model}")
        llm_logger.info(f"【消息轮次】{len(messages)} 条")
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            llm_logger.info(f"【消息{i+1}-{role}】\n{content}")

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
        except Exception as e:
            llm_logger.error(f"【多轮对话网络异常】{e}")
            raise RuntimeError(f"调用 {self.provider_name} API网络请求失败: {e}") from e

        if response.status_code != 200:
            error_msg = f"API返回错误状态码: {response.status_code}, {response.text}"
            llm_logger.error(f"【多轮对话API错误】{error_msg}")
            raise ValueError(error_msg)

        result = response.json()
        if 'choices' not in result or not result['choices']:
            error_msg = f"API响应缺少choices字段: {result}"
            llm_logger.error(f"【多轮对话响应异常】{error_msg}")
            raise ValueError(error_msg)

        raw_sql = result['choices'][0]['message']['content'].strip()
        sql = self._extract_sql(raw_sql)

        elapsed_time = time.time() - start_time

        prompt_tokens = result.get('usage', {}).get('prompt_tokens', 0)
        completion_tokens = result.get('usage', {}).get('completion_tokens', 0)
        total_tokens = result.get('usage', {}).get('total_tokens', 0)

        llm_logger.info(f"【多轮对话响应】\n{raw_sql}")
        llm_logger.info(f"【提取SQL】\n{sql}")
        llm_logger.info(f"【Token消耗】输入: {prompt_tokens}, 输出: {completion_tokens}, 总计: {total_tokens}")
        llm_logger.info(f"【耗时】{elapsed_time:.2f}秒")

        return {
            'sql': sql,
            'raw_response': raw_sql,
            'provider': self.provider,
            'model': self.model,
            'duration_ms': round(elapsed_time * 1000, 2),
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens
        }

    def test_connection(self) -> dict:
        """测试API连接"""
        try:
            if not self.api_key:
                return {'success': False, 'message': 'API密钥未配置'}

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 10
            }

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                return {'success': True, 'message': f'{self.provider_name} API连接成功'}
            else:
                return {'success': False, 'message': f'API返回错误: {response.status_code} - {response.text[:200]}'}
        except Exception as e:
            return {'success': False, 'message': f'连接失败: {str(e)}'}
