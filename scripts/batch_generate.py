# -*- coding: UTF-8 -*-
"""
批量SQL生成脚本 - 支持多模型轮询调用

用法：
    python scripts/batch_generate.py

功能：
    - 输入数据集编号（如 db1, db2）
    - 读取 scripts/db{n}/dataset.json 中的问题
    - 使用环境变量 BATCH_DB_USERNAME / BATCH_DB_PASSWORD 指定的账号登录
    - 轮询调用多个模型配置
    - 支持断点继续
    - 捕捉上下文大小不足、额度用完等错误
    - 保存结果到 scripts/db{n}/results.json
    - 保存日志到 scripts/db{n}/batch_log.txt
"""
import json
import os
import re
import time
import requests
from datetime import datetime
from typing import List, Dict, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_DIR = SCRIPT_DIR

BASE_URL = "http://localhost:8188"

CONTEXT_TOO_LARGE_PATTERNS = [
    r"error code",
    r"free",
    r"quota exceeded",
]

QUOTA_EXHAUSTED_PATTERNS = [
    r"quota.*exhausted",
    r"rate.*limit",
    r"too many requests",
    r"insufficient.*quota",
    r"余额.*不足",
    r"额度.*用完",
    r"超出.*限制",
    r"429",
]


def get_db_config(db_name: str) -> dict:
    """获取数据库配置（凭据从环境变量读取，禁止硬编码）"""
    db_path = os.path.join(DB_DIR, db_name)
    username = os.getenv("BATCH_DB_USERNAME", "")
    password = os.getenv("BATCH_DB_PASSWORD", "")
    if not username or not password:
        raise SystemExit(
            "缺少批量生成凭据: 请设置环境变量 BATCH_DB_USERNAME / BATCH_DB_PASSWORD")
    return {
        "username": username,
        "password": password,
        "dataset_file": os.path.join(db_path, "dataset.json"),
        "results_file": os.path.join(db_path, "results.json"),
        "log_file": os.path.join(db_path, "batch_log.txt"),
        "progress_file": os.path.join(db_path, "progress.json"),
        "model_configs_file": os.path.join(db_path, "model_configs.json"),
        "db_path": db_path
    }


class TokenManager:
    """Token管理器 - 自动刷新过期token"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._token = None
        self._login()
    
    def _login(self):
        """登录获取token"""
        response = requests.post(
            f"{BASE_URL}/login",
            json={"username": self.username, "password": self.password}
        )
        if response.status_code == 200:
            data = response.json()
            self._token = data.get("access_token")
            print(f"  [Token] 登录成功，获取新token")
        else:
            raise Exception(f"登录失败: {response.text}")
    
    def get_token(self) -> str:
        """获取当前token"""
        return self._token
    
    def refresh(self):
        """刷新token"""
        print("  [Token] Token已过期，正在刷新...")
        self._login()
    
    def is_token_expired(self, response: requests.Response) -> bool:
        """检查响应是否表示token过期"""
        return response.status_code == 401


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


def get_llm_configs(token: str) -> List[Dict]:
    """获取用户的LLM配置列表（仅返回有效配置）"""
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
            all_configs = response.json().get("items", [])
            active_configs = [cfg for cfg in all_configs if cfg.get("is_active", True)]
            return active_configs
        return []
    except Exception:
        return []


def generate_sql_with_model(token_manager: 'TokenManager', question: str, schema_name: str, 
                            db_type: str, llm_config_id: int, timeout: int = 300, retry_count: int = 2):
    """调用SQL生成API，指定模型配置（支持token自动刷新）"""
    for attempt in range(retry_count):
        token = token_manager.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "query": question,
            "schema_name": schema_name,
            "db_type": db_type,
            "llm_config_id": llm_config_id
        }
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/chat-to-sql/generate_sql",
                headers=headers,
                json=payload,
                timeout=timeout
            )
            
            if token_manager.is_token_expired(response):
                token_manager.refresh()
                continue
            
            return response
        except requests.exceptions.Timeout:
            return None
        except Exception as e:
            return None
    
    return None


def is_context_too_large(error_msg: str) -> bool:
    """检查是否是上下文过大错误"""
    error_lower = error_msg.lower()
    for pattern in CONTEXT_TOO_LARGE_PATTERNS:
        if re.search(pattern, error_lower, re.IGNORECASE):
            return True
    return False


def is_quota_exhausted(error_msg: str) -> bool:
    """检查是否是额度用完错误"""
    error_lower = error_msg.lower()
    for pattern in QUOTA_EXHAUSTED_PATTERNS:
        if re.search(pattern, error_lower, re.IGNORECASE):
            return True
    return False


def load_dataset(file_path: str):
    """加载数据集"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_progress(progress_file: str) -> dict:
    """加载进度"""
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": 0, "results": []}


def save_progress(progress_file: str, last_index: int, results: list):
    """保存进度"""
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump({"last_index": last_index, "results": results}, f, ensure_ascii=False)


def save_results(results: list, file_path: str):
    """保存结果"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def log_message(message: str, log_file: str):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


class ModelRotator:
    """模型轮询器"""
    
    def __init__(self, configs: List[Dict], token_manager: 'TokenManager' = None):
        self.configs = configs
        self.current_index = 0
        self.exhausted_configs = set()
        self.context_error_configs = set()
        self.error_configs = set()
        self.token_manager = token_manager
    
    def get_next_config(self) -> Optional[Dict]:
        """获取下一个可用配置"""
        if not self.configs:
            return None
        
        attempts = 0
        while attempts < len(self.configs):
            config = self.configs[self.current_index]
            config_id = config.get("id")
            
            self.current_index = (self.current_index + 1) % len(self.configs)
            
            if (config_id not in self.exhausted_configs and 
                config_id not in self.context_error_configs and
                config_id not in self.error_configs):
                return config
            
            attempts += 1
        
        return None
    
    def mark_quota_exhausted(self, config_id: int):
        """标记配置额度用完"""
        self.exhausted_configs.add(config_id)
        print(f"    [模型轮换] 配置 {config_id} 额度用完，切换下一个模型")
    
    def mark_context_error(self, config_id: int):
        """标记配置上下文错误"""
        self.context_error_configs.add(config_id)
        print(f"    [模型轮换] 配置 {config_id} 上下文过大，切换下一个模型")
    
    def mark_error(self, config_id: int, error_msg: str = ""):
        """标记配置执行出错，并更新数据库状态"""
        self.error_configs.add(config_id)
        print(f"    [模型轮换] 配置 {config_id} 执行出错，已标记为不可用")
        
        if self.token_manager:
            try:
                token = self.token_manager.get_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                response = requests.put(
                    f"{BASE_URL}/api/llm-config/{config_id}",
                    headers=headers,
                    json={"is_active": False},
                    timeout=10
                )
                if response.status_code == 200:
                    print(f"    [数据库更新] 配置 {config_id} 已设置为不可用")
                else:
                    print(f"    [数据库更新] 配置 {config_id} 更新失败: {response.text[:100]}")
            except Exception as e:
                print(f"    [数据库更新] 配置 {config_id} 更新异常: {str(e)[:100]}")
    
    def available_count(self) -> int:
        """获取可用配置数量"""
        return len(self.configs) - len(self.exhausted_configs) - len(self.context_error_configs) - len(self.error_configs)
    
    def reset_context_errors(self):
        """重置上下文错误（新问题可以重试）"""
        self.context_error_configs.clear()


def main():
    """主函数"""
    print("=" * 60)
    print("QueryForge 批量SQL生成脚本 (多模型轮询版)")
    print("=" * 60)
    
    db_name = input("请输入数据集编号（如 db1, db2）: ").strip()
    if not db_name:
        print("错误: 必须输入数据集编号")
        return
    
    config = get_db_config(db_name)
    
    if not os.path.exists(config["dataset_file"]):
        print(f"错误: 数据集文件不存在: {config['dataset_file']}")
        return
    
    print(f"\n配置信息:")
    print(f"  用户名: {config['username']}")
    print(f"  数据集: {config['dataset_file']}")
    print(f"  结果文件: {config['results_file']}")
    print(f"  日志文件: {config['log_file']}")
    print(f"  进度文件: {config['progress_file']}")
    
    resume = "n"
    if os.path.exists(config["progress_file"]):
        resume = input("\n发现进度文件，是否继续上次任务? (y/n): ").strip().lower()
    
    if resume == 'y':
        print("将继续上次任务...")
    else:
        confirm = input("\n确认开始新任务? (y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
        
        if os.path.exists(config["progress_file"]):
            os.remove(config["progress_file"])
    
    log_file = config["log_file"]
    
    log_message("=" * 60, log_file)
    log_message(f"开始批量SQL生成任务 - {db_name}", log_file)
    log_message("=" * 60, log_file)
    
    dataset = load_dataset(config["dataset_file"])
    total = len(dataset)
    log_message(f"共加载 {total} 条问题", log_file)
    
    try:
        token_manager = TokenManager(config["username"], config["password"])
        log_message("登录成功", log_file)
    except Exception as e:
        log_message(f"登录失败: {e}", log_file)
        return
    
    token = token_manager.get_token()
    llm_configs = get_llm_configs(token)
    if not llm_configs:
        log_message("错误: 没有可用的LLM配置，请先运行 setup_models.py 配置模型", log_file)
        return
    
    log_message(f"加载到 {len(llm_configs)} 个模型配置", log_file)
    for cfg in llm_configs:
        log_message(f"  - {cfg['provider']}/{cfg['model']} (ID: {cfg['id']})", log_file)
    
    rotator = ModelRotator(llm_configs, token_manager)
    
    start_index = 0
    results = []
    
    if resume == 'y':
        progress = load_progress(config["progress_file"])
        start_index = progress.get("last_index", 0)
        results = progress.get("results", [])
        log_message(f"从第 {start_index + 1} 条继续", log_file)
    
    success_count = len([r for r in results if r.get("status") == "success"])
    error_count = len([r for r in results if r.get("status") != "success"])
    
    for idx in range(start_index, total):
        item = dataset[idx]
        instance_id = item.get("instance_id", idx + 1)
        schema_name = item.get("db_id", "")
        db_type = item.get("db_type", "sqlite")
        question = item.get("question", "")
        
        log_message(f"\n[{idx + 1}/{total}] 处理问题 #{instance_id}", log_file)
        log_message(f"  schema: {schema_name}", log_file)
        log_message(f"  question: {question[:80]}...", log_file)
        
        rotator.reset_context_errors()
        
        result = None
        attempts = 0
        max_attempts = rotator.available_count()
        
        while attempts < max_attempts:
            model_config = rotator.get_next_config()
            if not model_config:
                log_message("  没有可用的模型配置", log_file)
                break
            
            attempts += 1
            config_id = model_config.get("id")
            model_name = f"{model_config['provider']}/{model_config['model']}"
            
            log_message(f"  尝试模型 [{attempts}/{max_attempts}]: {model_name}", log_file)
            
            start_time = time.time()
            
            try:
                response = generate_sql_with_model(
                    token_manager, question, schema_name, db_type, config_id
                )
                elapsed = time.time() - start_time
                
                if response is None:
                    log_message(f"    请求超时", log_file)
                    continue
                
                if response.status_code == 200:
                    data = response.json()
                    result = {
                        "instance_id": instance_id,
                        "db_id": schema_name,
                        "question": question,
                        "sql": data.get("sql_query", ""),
                        "is_valid": data.get("is_valid", False),
                        "error_message": data.get("error_message"),
                        "columns": data.get("columns"),
                        "elapsed_seconds": round(elapsed, 2),
                        "status": "success",
                        "model": model_name,
                        "config_id": config_id
                    }
                    success_count += 1
                    log_message(f"    成功! 耗时: {elapsed:.2f}s", log_file)
                    log_message(f"    SQL: {result['sql'][:100]}...", log_file)
                    break
                
                else:
                    error_text = response.text
                    error_msg = f"API错误: {response.status_code} - {error_text[:200]}"
                    
                    if is_quota_exhausted(error_text):
                        rotator.mark_quota_exhausted(config_id)
                        log_message(f"    额度用完，切换模型", log_file)
                        continue
                    
                    if is_context_too_large(error_text):
                        rotator.mark_context_error(config_id)
                        log_message(f"    上下文过大，切换模型", log_file)
                        continue
                    
                    rotator.mark_error(config_id, error_msg)
                    log_message(f"    失败: {error_msg[:100]}", log_file)
                    continue
            
            except Exception as e:
                elapsed = time.time() - start_time
                error_msg = str(e)
                
                if is_quota_exhausted(error_msg):
                    rotator.mark_quota_exhausted(config_id)
                    log_message(f"    额度用完，切换模型", log_file)
                    continue
                
                if is_context_too_large(error_msg):
                    rotator.mark_context_error(config_id)
                    log_message(f"    上下文过大，切换模型", log_file)
                    continue
                
                rotator.mark_error(config_id, error_msg)
                log_message(f"    异常: {error_msg[:100]}", log_file)
                continue
        
        if result is None:
            result = {
                "instance_id": instance_id,
                "db_id": schema_name,
                "question": question,
                "sql": "",
                "is_valid": False,
                "error_message": "所有模型配置都不可用",
                "elapsed_seconds": 0,
                "status": "no_model",
                "model": None,
                "config_id": None
            }
            error_count += 1
        
        results.append(result)
        
        save_progress(config["progress_file"], idx + 1, results)
        
        if (idx + 1) % 10 == 0:
            save_results(results, config["results_file"])
            log_message(f"  已保存中间结果 ({idx + 1}/{total})", log_file)
            log_message(f"  当前统计: 成功 {success_count}, 失败 {error_count}", log_file)
            log_message(f"  可用模型: {rotator.available_count()}/{len(llm_configs)}", log_file)
        
        time.sleep(0.3)
    
    save_results(results, config["results_file"])
    
    if os.path.exists(config["progress_file"]):
        os.remove(config["progress_file"])
    
    log_message("=" * 60, log_file)
    log_message("批量任务完成!", log_file)
    log_message(f"总数: {total}, 成功: {success_count}, 失败: {error_count}", log_file)
    log_message(f"结果已保存到: {config['results_file']}", log_file)
    log_message("=" * 60, log_file)
    
    print(f"\n完成! 结果保存在: {config['results_file']}")


if __name__ == "__main__":
    main()
