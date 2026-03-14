import os
import requests
import time
from app.logger import logger, llm_logger


class LLMClient:
    """大模型客户端（集成智谱AI GLM-4.5模型）"""

    def __init__(self, api_key: str = "", max_tokens: int = 8000, timeout: int = 300):
        """
        初始化客户端
        :param api_key: 智谱AI API密钥
        :param max_tokens: 生成SQL的最大token数
        :param timeout: 请求超时时间（秒）
        """
        self.api_key = api_key or os.getenv('ZHIPU_API_KEY', '')
        self.model = "GLM-4.5"
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.max_tokens = max_tokens
        self.timeout = timeout

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
        """调用智谱AI GLM-4.5模型真实API，失败时抛出异常（无重试）"""
        if not self.api_key:
            raise ValueError("未配置智谱AI API密钥，请设置 ZHIPU_API_KEY 环境变量")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": self.max_tokens
        }

        logger.info("调用AI API...")
        start_time = time.time()
        
        llm_logger.info(f"【请求模型】{self.model}")
        llm_logger.info(f"【发送内容】\n{prompt}")
        
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
            raise RuntimeError(f"调用AI API网络请求失败: {e}") from e

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
        
        prompt_tokens = result.get('usage', {}).get('prompt_tokens', 'N/A')
        completion_tokens = result.get('usage', {}).get('completion_tokens', 'N/A')
        total_tokens = result.get('usage', {}).get('total_tokens', 'N/A')
        
        logger.info(f"LLM调用完成 - 耗时: {elapsed_time:.2f}s, 输入tokens: {prompt_tokens}, 输出tokens: {completion_tokens}, 总tokens: {total_tokens}")
        
        llm_logger.info(f"【响应内容】\n{raw_sql}")
        llm_logger.info(f"【提取SQL】\n{sql}")
        llm_logger.info(f"【Token消耗】输入: {prompt_tokens}, 输出: {completion_tokens}, 总计: {total_tokens}")
        llm_logger.info(f"【耗时】{elapsed_time:.2f}秒")
        
        return sql
