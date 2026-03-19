# -*- coding: UTF-8 -*-
"""
批量SQL生成脚本

用法：
    python scripts/batch_generate.py

功能：
    - 输入 db 编号（如 db1, db2）
    - 读取 db/db{n}/dataset.json 中的问题
    - 使用 db{n} 用户登录（密码: 123456）
    - 批量调用 SQL 生成 API
    - 保存结果到 db/db{n}/results.json
    - 保存日志到 db/db{n}/batch_log.txt
"""
import json
import os
import time
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_DIR = SCRIPT_DIR

BASE_URL = "http://localhost:8188"


def get_db_config(db_name: str) -> dict:
    """获取数据库配置"""
    db_path = os.path.join(DB_DIR, db_name)
    return {
        "username": db_name,
        "password": "123456",
        "dataset_file": os.path.join(db_path, "dataset.json"),
        "results_file": os.path.join(db_path, "results.json"),
        "log_file": os.path.join(db_path, "batch_log.txt"),
        "db_path": db_path
    }


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


def load_dataset(file_path: str):
    """加载数据集"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


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


def main():
    """主函数"""
    print("=" * 60)
    print("QueryForge 批量SQL生成脚本")
    print("=" * 60)
    
    db_name = input("请输入 db 编号（如 db1, db2）: ").strip()
    if not db_name:
        print("错误: 必须输入 db 编号")
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
    
    confirm = input("\n确认开始? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    log_file = config["log_file"]
    
    log_message("=" * 60, log_file)
    log_message(f"开始批量SQL生成任务 - {db_name}", log_file)
    log_message("=" * 60, log_file)
    
    dataset = load_dataset(config["dataset_file"])
    total = len(dataset)
    log_message(f"共加载 {total} 条问题", log_file)
    
    try:
        token = login(config["username"], config["password"])
        log_message("登录成功", log_file)
    except Exception as e:
        log_message(f"登录失败: {e}", log_file)
        return
    
    results = []
    success_count = 0
    error_count = 0
    
    for idx, item in enumerate(dataset, 1):
        instance_id = item.get("instance_id", idx)
        db_id = item.get("db_id", "")
        db_type = item.get("db_type", "sqlite")
        question = item.get("question", "")
        
        log_message(f"[{idx}/{total}] 处理问题 #{instance_id}", log_file)
        log_message(f"  db_id: {db_id}", log_file)
        log_message(f"  question: {question[:80]}...", log_file)
        
        start_time = time.time()
        
        try:
            response = generate_sql(token, question, db_id, db_type)
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                result = {
                    "instance_id": instance_id,
                    "db_id": db_id,
                    "question": question,
                    "sql": data.get("sql_query", ""),
                    "is_valid": data.get("is_valid", False),
                    "error_message": data.get("error_message"),
                    "columns": data.get("columns"),
                    "elapsed_seconds": round(elapsed, 2),
                    "status": "success"
                }
                success_count += 1
                log_message(f"  成功! 耗时: {elapsed:.2f}s", log_file)
                log_message(f"  SQL: {result['sql'][:100]}...", log_file)
            else:
                result = {
                    "instance_id": instance_id,
                    "db_id": db_id,
                    "question": question,
                    "sql": "",
                    "is_valid": False,
                    "error_message": f"API错误: {response.status_code} - {response.text}",
                    "elapsed_seconds": round(elapsed, 2),
                    "status": "error"
                }
                error_count += 1
                log_message(f"  失败: {response.status_code}", log_file)
                
                log_message("=" * 60, log_file)
                log_message(f"处理失败，是否继续? (y/n): ", log_file)
                print(f"\n失败: {response.status_code} - {response.text[:200]}")
                cont = input("处理失败，是否继续? (y/n): ").strip().lower()
                if cont != 'y':
                    log_message("用户选择停止", log_file)
                    break
        
        except Exception as e:
            elapsed = time.time() - start_time
            result = {
                "instance_id": instance_id,
                "db_id": db_id,
                "question": question,
                "sql": "",
                "is_valid": False,
                "error_message": str(e),
                "elapsed_seconds": round(elapsed, 2),
                "status": "exception"
            }
            error_count += 1
            log_message(f"  异常: {e}", log_file)
            
            log_message("=" * 60, log_file)
            log_message(f"处理异常，是否继续? (y/n): ", log_file)
            print(f"\n异常: {e}")
            cont = input("处理异常，是否继续? (y/n): ").strip().lower()
            if cont != 'y':
                log_message("用户选择停止", log_file)
                break
        
        results.append(result)
        
        if idx % 10 == 0:
            save_results(results, config["results_file"])
            log_message(f"  已保存中间结果 ({idx}/{total})", log_file)
        
        time.sleep(0.5)
    
    save_results(results, config["results_file"])
    
    log_message("=" * 60, log_file)
    log_message("批量任务完成!", log_file)
    log_message(f"总数: {total}, 成功: {success_count}, 失败: {error_count}", log_file)
    log_message(f"结果已保存到: {config['results_file']}", log_file)
    log_message("=" * 60, log_file)
    
    print(f"\n完成! 结果保存在: {config['results_file']}")


if __name__ == "__main__":
    main()
