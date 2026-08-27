# -*- coding: UTF-8 -*-
"""
LLM客户端 - 通用大模型API调用

安全：SSRF 防护 — base_url 仅允许 http/https 且禁止指向内网地址
性能：requests.Session 连接池复用，减少建连开销
"""
import ipaddress
import json
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.logger import llm_logger


# ── SSRF 防护 ──────────────────────────────────────────────

# 禁止访问的内网 IP 范围
_BLOCKED_CIDRS = [
    ipaddress.ip_network('127.0.0.0/8'),       # loopback
    ipaddress.ip_network('10.0.0.0/8'),        # private A
    ipaddress.ip_network('172.16.0.0/12'),     # private B
    ipaddress.ip_network('192.168.0.0/16'),    # private C
    ipaddress.ip_network('169.254.0.0/16'),    # link-local (云元数据服务)
    ipaddress.ip_network('0.0.0.0/8'),         # current network
]


def _validate_llm_url(url: str) -> None:
    """校验 LLM API URL — 防止 SSRF 攻击

    规则：
    1) 必须是 http 或 https scheme
    2) 不能指向内网地址（127.x / 10.x / 172.16-31.x / 192.168.x / 169.254.x）
    3) 不能使用 localhost / 0.0.0.0
    """
    if not url:
        raise ValueError("LLM API 地址未配置")

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(
            f"LLM API 地址 scheme 不合法: {parsed.scheme}，仅允许 http/https"
        )

    hostname = parsed.hostname or ''
    if hostname.lower() in ('localhost', '0.0.0.0'):
        raise ValueError(f"LLM API 地址不允许指向 {hostname}")

    # 尝试解析为 IP 地址（域名跳过 IP 检查，DNS 在请求时解析）
    try:
        ip = ipaddress.ip_address(hostname)
        for cidr in _BLOCKED_CIDRS:
            if ip in cidr:
                raise ValueError(
                    f"LLM API 地址不允许指向内网地址 {ip}（禁止 {cidr}）"
                )
    except ValueError as e:
        if "doesn't appear to be an IPv" in str(e) or "does not appear to be an IPv" in str(e):
            pass  # 是域名不是 IP，放行（DNS 在请求时解析）
        else:
            raise  # 是内网 IP，拒绝


# ── 连接池 Session ──────────────────────────────────────────
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """获取共享 Session（连接池复用）"""
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=5,
            pool_maxsize=10,
            max_retries=Retry(total=2, backoff_factor=0.5,
                              status_forcelist=[502, 503, 504]),
        )
        _session.mount('http://', adapter)
        _session.mount('https://', adapter)
    return _session


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
        :param base_url: API地址（仅允许 http/https 且禁止内网地址）
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

    def call_llm_json(self, prompt: str) -> dict:
        """调用大模型 API 并解析 JSON 响应（用于结构化判断，如「可否生成 SQL」）

        解析策略（容错）：
          1. 去掉 ```json / ``` 代码块包裹
          2. 截取首个 '{' 到最后一个 '}' 的子串做 json.loads
          3. 解析失败 → 返回 {"can_generate": true, "reason": "..."} 默认放行，
             保证判断步故障不阻断主生成流程（宁可放过，不可误拦）

        Returns:
            dict: 含原始 JSON 字段 + _judge_tokens（token 统计）
        """
        result = self.call_llm_with_details(prompt)
        raw = (result.get('raw_response') or '').strip()

        # 去掉 markdown 代码块包裹
        cleaned = raw
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        elif cleaned.startswith('```'):
            cleaned = cleaned[3:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # 截取首个 { 到最后一个 } 之间的 JSON 文本
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        tokens_meta = {
            'prompt_tokens': result.get('prompt_tokens', 0),
            'completion_tokens': result.get('completion_tokens', 0),
            'total_tokens': result.get('total_tokens', 0),
        }
        if start != -1 and end != -1 and end > start:
            json_str = cleaned[start:end + 1]
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    parsed.setdefault('_judge_tokens', tokens_meta)
                    parsed.setdefault('_judge_raw', raw)
                    return parsed
            except json.JSONDecodeError as e:
                llm_logger.warning(f"【JSON 解析失败】{e} | raw: {raw[:200]}")
        else:
            llm_logger.warning(f"【JSON 响应未找到对象边界】raw: {raw[:200]}")

        # 兜底：默认放行，避免判断步故障阻断生成
        return {
            'can_generate': True,
            'reason': '可行性判断响应解析失败，默认放行进入生成流程',
            'missing_info': [],
            'suggestion': '',
            '_judge_tokens': tokens_meta,
            '_judge_raw': raw,
        }

    def call_llm_with_details(self, prompt: str) -> dict:
        """调用大模型API，返回详细信息"""
        if not self.api_key:
            raise ValueError(f"未配置 {self.provider_name} API密钥，请设置环境变量或在前端配置")

        _validate_llm_url(self.base_url)  # SSRF 防护

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
            response = _get_session().post(
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

        _validate_llm_url(self.base_url)  # SSRF 防护

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
            response = _get_session().post(
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

            _validate_llm_url(self.base_url)  # SSRF 防护

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 10
            }

            response = _get_session().post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                return {'success': True, 'message': f'{self.provider_name} API连接成功'}
            else:
                return {'success': False, 'message': f'API返回错误: {response.status_code} - {response.text[:200]}'}
        except ValueError as e:
            return {'success': False, 'message': f'URL校验失败: {e}'}
        except Exception as e:
            return {'success': False, 'message': f'连接失败: {str(e)}'}
