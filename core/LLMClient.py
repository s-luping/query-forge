# -*- coding: UTF-8 -*-
"""
多模型LLM客户端 - 支持GLM、Qwen、DeepSeek、Doubao等主流大模型
"""
import os
import requests
import time
from app.logger import logger, llm_logger


class LLMClient:
    """多模型大模型客户端"""

    MODEL_CONFIGS = {
        'glm': {
            'name': '智谱GLM',
            'default_model': 'GLM-4.5',
            'base_url': 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
            'auth_prefix': 'Bearer',
            'models': ['GLM-4.5', 'GLM-4', 'GLM-3-Turbo']
        },
        'qwen': {
            'name': '阿里通义千问',
            'default_model': 'qwen-plus',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
            'auth_prefix': 'Bearer',
            'models': ['qwen-turbo', 'qwen-plus', 'qwen-max', 'qwen-max-longcontext']
        },
        'deepseek': {
            'name': 'DeepSeek',
            'default_model': 'deepseek-chat',
            'base_url': 'https://api.deepseek.com/v1/chat/completions',
            'auth_prefix': 'Bearer',
            'models': ['deepseek-chat', 'deepseek-coder']
        },
        'doubao': {
            'name': '字节豆包',
            'default_model': 'doubao-pro-32k',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
            'auth_prefix': 'Bearer',
            'models': ['doubao-pro-32k', 'doubao-pro-128k', 'doubao-lite-32k']
        },
        'openai': {
            'name': 'OpenAI',
            'default_model': 'gpt-4o',
            'base_url': 'https://api.openai.com/v1/chat/completions',
            'auth_prefix': 'Bearer',
            'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo']
        }
    }

    def __init__(self, provider: str = 'glm', api_key: str = "", model: str = None, 
                 max_tokens: int = 8000, timeout: int = 300, temperature: float = 0.7):
        """
        初始化客户端
        :param provider: 模型提供商 (glm, qwen, deepseek, doubao, openai)
        :param api_key: API密钥
        :param model: 模型名称，不指定则使用默认
        :param max_tokens: 最大生成token数
        :param timeout: 请求超时时间（秒）
        :param temperature: 生成随机性 (0-2)
        """
        self.provider = provider.lower() if provider else 'glm'
        
        if self.provider not in self.MODEL_CONFIGS:
            raise ValueError(f"不支持的模型提供商: {provider}，支持的提供商: {list(self.MODEL_CONFIGS.keys())}")
        
        self.config = self.MODEL_CONFIGS[self.provider]
        self.api_key = api_key or os.getenv(f'{self.provider.upper()}_API_KEY', '') or os.getenv('ZHIPU_API_KEY', '')
        self.model = model or self.config['default_model']
        self.base_url = self.config['base_url']
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
            raise ValueError(f"未配置 {self.config['name']} API密钥，请设置环境变量或在前端配置")

        headers = {
            "Authorization": f"{self.config['auth_prefix']} {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        logger.info(f"调用 {self.config['name']} API...")
        start_time = time.time()
        
        llm_logger.info(f"【请求模型】{self.config['name']} - {self.model}")
        llm_logger.info(f"【发送内容】\n{prompt[:500]}...")
        
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
        except Exception as e:
            logger.error(f"网络请求异常: {e}")
            llm_logger.error(f"【网络请求异常】{e}")
            raise RuntimeError(f"调用 {self.config['name']} API网络请求失败: {e}") from e

        if response.status_code != 200:
            error_msg = f"API返回错误状态码: {response.status_code}, {response.text}"
            logger.error(error_msg)
            llm_logger.error(f"【API错误】{error_msg}")
            raise ValueError(error_msg)

        result = response.json()
        if 'choices' not in result or not result['choices']:
            error_msg = f"API响应缺少choices字段: {result}"
            logger.error(error_msg)
            llm_logger.error(f"【响应异常】{error_msg}")
            raise ValueError(error_msg)

        raw_sql = result['choices'][0]['message']['content'].strip()
        sql = self._extract_sql(raw_sql)
        
        elapsed_time = time.time() - start_time
        
        prompt_tokens = result.get('usage', {}).get('prompt_tokens', 0)
        completion_tokens = result.get('usage', {}).get('completion_tokens', 0)
        total_tokens = result.get('usage', {}).get('total_tokens', 0)
        
        logger.info(f"LLM调用完成 - 耗时: {elapsed_time:.2f}s, 输入tokens: {prompt_tokens}, 输出tokens: {completion_tokens}, 总tokens: {total_tokens}")
        
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

    def test_connection(self) -> dict:
        """测试API连接"""
        try:
            if not self.api_key:
                return {'success': False, 'message': 'API密钥未配置'}
            
            headers = {
                "Authorization": f"{self.config['auth_prefix']} {self.api_key}",
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
                return {'success': True, 'message': f'{self.config["name"]} API连接成功'}
            else:
                return {'success': False, 'message': f'API返回错误: {response.status_code} - {response.text[:200]}'}
        except Exception as e:
            return {'success': False, 'message': f'连接失败: {str(e)}'}

    @classmethod
    def get_supported_providers(cls) -> list:
        """获取支持的模型提供商列表"""
        return [
            {
                'provider': key,
                'name': config['name'],
                'default_model': config['default_model'],
                'models': config['models']
            }
            for key, config in cls.MODEL_CONFIGS.items()
        ]
