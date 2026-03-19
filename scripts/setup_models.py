# -*- coding: UTF-8 -*-
"""
模型配置脚本 - 批量配置 Qwen 和 Doubao 模型

用法：
    python scripts/setup_models.py

功能：
    - 配置多个 Qwen 和 Doubao 模型
    - 测试每个模型的连接
    - 只保存有效的模型配置
"""
import json
import os
import sys
import time
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from models import AppSessionLocal
from models.llm_config import LLMConfig

BASE_URL = "http://localhost:8188"

API_FILE = os.path.join(SCRIPT_DIR, "api.txt")
QWEN_API_KEY = ""
DOUBAO_API_KEY = ""


def load_api_keys():
    """从 api.txt 加载 API Key"""
    global QWEN_API_KEY, DOUBAO_API_KEY
    
    if os.path.exists(API_FILE):
        with open(API_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if ":" in line:
                    provider, key = line.split(":", 1)
                    if provider.lower() == "qwen":
                        QWEN_API_KEY = key
                    elif provider.lower() == "doubao":
                        DOUBAO_API_KEY = key
        print(f"从 {API_FILE} 加载 API Key")
        print(f"  Qwen: {'已配置' if QWEN_API_KEY else '未配置'}")
        print(f"  Doubao: {'已配置' if DOUBAO_API_KEY else '未配置'}")

QWEN_MODELS = [
    {"model": "qwen-vl-ocr-2025-11-20", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-vl-max-2025-04-02", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-vl-max-1119", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-math-turbo", "max_tokens": 8000, "context": 4096},
    {"model": "qwen1.5-110b-chat", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-math-7b-instruct", "max_tokens": 8000, "context": 4096},
    {"model": "qwen-vl-plus-2025-05-07", "max_tokens": 8000, "context": 32000},
    {"model": "tongyi-intent-detect-v3", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-max-1230", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-plus-2025-07-28", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2-72b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-vl-3b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "deepseek-r1-distill-qwen-7b", "max_tokens": 8000, "context": 64000},
    {"model": "qwen2.5-14b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-mt-flash", "max_tokens": 8000, "context": 32000},
    {"model": "qwq-plus-latest", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-vl-7b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-ocr-latest", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-vl-plus-0102", "max_tokens": 8000, "context": 32000},
    {"model": "deepseek-v3.1", "max_tokens": 8000, "context": 64000},
    {"model": "qwen1.5-7b-chat", "max_tokens": 8000, "context": 128000},
    {"model": "deepseek-r1-distill-qwen-32b", "max_tokens": 8000, "context": 64000},
    {"model": "qwen-math-plus-0816", "max_tokens": 8000, "context": 4096},
    {"model": "tongyi-xiaomi-analysis-pro", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-long", "max_tokens": 8000, "context": 10000000},
    {"model": "qwen-coder-plus-latest", "max_tokens": 8000, "context": 128000},
    {"model": "qwq-32b-preview", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-72b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-3b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-plus-latest", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-turbo-2025-02-11", "max_tokens": 8000, "context": 128000},
    {"model": "opennlu-v1", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-plus-2025-09-11", "max_tokens": 8000, "context": 128000},
    {"model": "qwen3-vl-flash-2026-01-22", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-vl-ocr-1028", "max_tokens": 8000, "context": 32000},
    {"model": "qwen3-vl-flash-2025-10-15", "max_tokens": 8000, "context": 32000},
    {"model": "qwen2.5-14b-instruct-1m", "max_tokens": 8000, "context": 1000000},
    {"model": "qwen-plus-0112", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-coder-7b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2-vl-72b-instruct", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-math-plus", "max_tokens": 8000, "context": 4096},
    {"model": "gui-plus", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-mt-lite", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-plus-2025-01-25", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2-57b-a14b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-plus-2025-01-25", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-turbo-2025-07-15", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-plus-2025-08-15", "max_tokens": 8000, "context": 32000},
    {"model": "qwen2.5-coder-14b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen1.5-14b-chat", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-math-turbo-0919", "max_tokens": 8000, "context": 4096},
    {"model": "deepseek-r1", "max_tokens": 8000, "context": 64000},
    {"model": "qwen-turbo-2025-04-28", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-coder-turbo", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-mt-plus", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-max-0919", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-math-plus-0919", "max_tokens": 8000, "context": 4096},
    {"model": "qwen2.5-32b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-ocr-2025-08-28", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-plus-2025-12-01", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-plus-character", "max_tokens": 8000, "context": 128000},
    {"model": "MiniMax-M2.1", "max_tokens": 8000, "context": 128000},
    {"model": "deepseek-r1-distill-qwen-14b", "max_tokens": 8000, "context": 64000},
    {"model": "gui-plus-2026-02-26", "max_tokens": 8000, "context": 128000},
    {"model": "deepseek-v3", "max_tokens": 8000, "context": 64000},
    {"model": "qwq-32b", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-plus-2025-04-28", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-mt-turbo", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-math-turbo-latest", "max_tokens": 8000, "context": 4096},
    {"model": "qwen-vl-max-2025-01-25", "max_tokens": 8000, "context": 32000},
    {"model": "qwen-long-2025-01-25", "max_tokens": 8000, "context": 10000000},
    {"model": "qwen-math-plus-latest", "max_tokens": 8000, "context": 4096},
    {"model": "qwen-plus-2025-07-14", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2-7b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-math-72b-instruct", "max_tokens": 8000, "context": 4096},
    {"model": "deepseek-r1-0528", "max_tokens": 8000, "context": 64000},
    {"model": "qwen-vl-ocr", "max_tokens": 8000, "context": 32000},
    {"model": "qwen2.5-coder-32b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-long-latest", "max_tokens": 8000, "context": 10000000},
    {"model": "qwq-plus-2025-03-05", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-vl-ocr-2025-04-13", "max_tokens": 8000, "context": 32000},
    {"model": "qwen1.5-32b-chat", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-max-0428", "max_tokens": 8000, "context": 128000},
    {"model": "qwen1.5-72b-chat", "max_tokens": 8000, "context": 128000},
    {"model": "qwen-plus-1220", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2-vl-2b-instruct", "max_tokens": 8000, "context": 32000},
    {"model": "qwen2-vl-7b-instruct", "max_tokens": 8000, "context": 32000},
    {"model": "qwen2.5-1.5b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "qwen2.5-0.5b-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "deepseek-r1-distill-llama-70b", "max_tokens": 8000, "context": 64000},
    {"model": "llama-4-maverick-17b-128e-instruct", "max_tokens": 8000, "context": 128000},
    {"model": "llama-4-scout-17b-16e-instruct", "max_tokens": 8000, "context": 128000},
]

DOUBAO_MODELS = [
    {"model": "doubao-seed-2-0-pro-260215", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-2-0-lite-260215", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-2-0-mini-260215", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-2-0-code-preview-260215", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-8-251228", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-code-preview-251028", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-6-lite-251015", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-6-flash-250828", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-6-vision-250815", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-6-251015", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-seed-1-6-250615", "max_tokens": 8000, "context": 256000},
    {"model": "doubao-1-5-pro-32k-250115", "max_tokens": 8000, "context": 128000},
    {"model": "doubao-1-5-lite-32k-250115", "max_tokens": 8000, "context": 32000},
    {"model": "doubao-1-5-pro-32k-character-250715", "max_tokens": 8000, "context": 32000},
    {"model": "doubao-lite-32k-character-250228", "max_tokens": 8000, "context": 32000},
]


def login(username: str, password: str):
    """登录获取token"""
    response = requests.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": password}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    else:
        raise Exception(f"登录失败: {response.text}")


def test_model_connection(token: str, provider: str, model: str, api_key: str) -> dict:
    """测试模型连接"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "max_tokens": 100,
        "timeout": 30
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/llm-config/test",
            headers=headers,
            json=payload,
            timeout=60
        )
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}


def create_config(token: str, provider: str, model: str, api_key: str, max_tokens: int = 8000) -> dict:
    """创建模型配置"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "timeout": 300,
        "is_default": False,
        "description": f"{provider} - {model}"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/llm-config/create",
            headers=headers,
            json=payload,
            timeout=30
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def get_existing_configs(token: str) -> list:
    """获取已存在的配置"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/llm-config/list",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            return response.json().get("items", [])
        return []
    except Exception:
        return []


def main():
    """主函数"""
    print("=" * 60)
    print("QueryForge 模型配置脚本")
    print("=" * 60)
    
    load_api_keys()
    
    if not QWEN_API_KEY and not DOUBAO_API_KEY:
        print("错误: 至少需要提供一个 API Key")
        print(f"请在 {API_FILE} 中配置 API Key")
        print("格式: qwen:your_api_key")
        print("      doubao:your_api_key")
        return
    
    users = ["admin"]
    
    for user in users:
        print(f"\n{'='*60}")
        print(f"配置用户: {user}")
        print("=" * 60)
        
        try:
            token = login(user, "REDACTED")
            print(f"登录成功: {user}")
        except Exception as e:
            print(f"登录失败: {e}")
            continue
        
        existing = get_existing_configs(token)
        existing_keys = {(c['provider'], c['model']) for c in existing}
        print(f"已存在配置: {len(existing)} 个")
        
        valid_configs = []
        
        if QWEN_API_KEY:
            print(f"\n测试 Qwen 模型...")
            for model_info in QWEN_MODELS:
                model = model_info["model"]
                if ("qwen", model) in existing_keys:
                    print(f"  [跳过] {model} - 已存在")
                    continue
                
                print(f"  测试 {model}...", end=" ")
                result = test_model_connection(token, "qwen", model, QWEN_API_KEY)
                
                if result.get("success"):
                    print("✓ 有效")
                    create_result = create_config(token, "qwen", model, QWEN_API_KEY, model_info["max_tokens"])
                    if create_result.get("id"):
                        valid_configs.append({
                            "provider": "qwen",
                            "model": model,
                            "config_id": create_result.get("id"),
                            "context": model_info["context"]
                        })
                        print(f"    已保存配置 ID: {create_result.get('id')}")
                    else:
                        print(f"    保存失败: {create_result}")
                else:
                    print(f"✗ 无效 - {result.get('message', '')[:50]}")
                
                time.sleep(0.5)
        
        if DOUBAO_API_KEY:
            print(f"\n测试 Doubao 模型...")
            for model_info in DOUBAO_MODELS:
                model = model_info["model"]
                if ("doubao", model) in existing_keys:
                    print(f"  [跳过] {model} - 已存在")
                    continue
                
                print(f"  测试 {model}...", end=" ")
                result = test_model_connection(token, "doubao", model, DOUBAO_API_KEY)
                
                if result.get("success"):
                    print("✓ 有效")
                    create_result = create_config(token, "doubao", model, DOUBAO_API_KEY, model_info["max_tokens"])
                    if create_result.get("id"):
                        valid_configs.append({
                            "provider": "doubao",
                            "model": model,
                            "config_id": create_result.get("id"),
                            "context": model_info["context"]
                        })
                        print(f"    已保存配置 ID: {create_result.get('id')}")
                    else:
                        print(f"    保存失败: {create_result}")
                else:
                    print(f"✗ 无效 - {result.get('message', '')[:50]}")
                
                time.sleep(0.5)
        
        config_file = os.path.join(SCRIPT_DIR, user, "model_configs.json")
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(valid_configs, f, ensure_ascii=False, indent=2)
        
        print(f"\n用户 {user} 有效配置数: {len(valid_configs)}")
        print(f"配置已保存到: {config_file}")
    
    print("\n" + "=" * 60)
    print("配置完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
