# -*- coding: UTF-8 -*-
"""
批量重试失败记录脚本

用法：
    python scripts/retry_failed.py

功能：
    - 读取 scripts/results.json 中的失败记录
    - 重新调用 SQL 生成 API
    - 更新结果到 scripts/results.json
"""
import json
import os
import time
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

BASE_URL = "http://localhost:8188"
RESULTS_FILE = os.path.join(SCRIPT_DIR, "results.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "retry_log.txt")

USERNAME = "test_user"
PASSWORD = os.environ.get("RETRY_PASSWORD", "")


def login():
    """登录获取token"""
    response = requests.post(
        f"{BASE_URL}/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    else:
        raise Exception(f"登录失败: {response.text}")


def generate_sql(token: str, question: str, db_id: str = None, db_type: str = "sqlite", max_retries: int = 3):
    """调用SQL生成API，支持重试"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "query": question,
        "db_type": db_type
    }
    
    if db_id:
        payload["schema_name"] = db_id
    
    last_error = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{BASE_URL}/api/chat-to-sql/generate_sql",
                headers=headers,
                json=payload,
                timeout=300
            )
            return response
        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                print(f"  请求超时，{wait_time}秒后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
        except Exception as e:
            last_error = e
            break
    
    raise last_error


def load_results():
    """加载已有结果"""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(results: list):
    """保存结果"""
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def log_message(message: str):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


def main():
    """主函数"""
    log_message("=" * 60)
    log_message("开始重试失败记录任务")
    log_message("=" * 60)
    
    results = load_results()
    total = len(results)
    
    failed_items = [r for r in results if r.get("status") != "success"]
    log_message(f"共加载 {total} 条记录，其中 {len(failed_items)} 条失败")
    
    if not failed_items:
        log_message("没有需要重试的记录")
        return
    
    token = login()
    log_message("登录成功")
    
    success_count = 0
    error_count = 0
    
    for idx, item in enumerate(failed_items, 1):
        instance_id = item.get("instance_id", "?")
        db_id = item.get("db_id", "")
        question = item.get("question", "")
        
        log_message(f"[{idx}/{len(failed_items)}] 重试问题 #{instance_id}")
        log_message(f"  question: {question[:60]}...")
        
        start_time = time.time()
        
        try:
            response = generate_sql(token, question, db_id)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                item["sql"] = data.get("sql_query", "")
                item["is_valid"] = data.get("is_valid", False)
                item["error_message"] = data.get("error_message")
                item["columns"] = data.get("columns")
                item["elapsed_seconds"] = round(elapsed, 2)
                item["status"] = "success"
                item["retry_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                success_count += 1
                log_message(f"  成功! 耗时: {elapsed:.2f}s")
            else:
                item["error_message"] = f"API错误: {response.status_code} - {response.text}"
                item["status"] = "error"
                item["retry_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                error_count += 1
                log_message(f"  失败: {response.status_code}")
        
        except Exception as e:
            elapsed = time.time() - start_time
            item["error_message"] = str(e)
            item["status"] = "exception"
            item["elapsed_seconds"] = round(elapsed, 2)
            item["retry_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_count += 1
            log_message(f"  异常: {e}")
        
        save_results(results)
        
        if idx % 10 == 0:
            log_message(f"  已保存中间结果")
        
        time.sleep(1)
    
    save_results(results)
    
    success_items = [r for r in results if r.get("status") == "success"]
    
    log_message("=" * 60)
    log_message("重试任务完成!")
    log_message(f"总数: {total}, 成功: {len(success_items)}, 失败: {total - len(success_items)}")
    log_message(f"本次重试: 成功 {success_count}, 失败 {error_count}")
    log_message(f"结果已保存到: {RESULTS_FILE}")
    log_message("=" * 60)


if __name__ == "__main__":
    main()
