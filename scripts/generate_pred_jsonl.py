# -*- coding: UTF-8 -*-
"""
生成 Spider 格式的预测结果文件 pred.jsonl
从 results.json 读取 SQL 查询，按指定格式输出
"""
import json
import os
import re
from pathlib import Path


def clean_sql(sql: str) -> str:
    """清理 SQL：去掉注释和多余换行符"""
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'\s+', ' ', sql)
    sql = sql.strip()
    sql = re.sub(r'\s*;\s*$', ';', sql)
    return sql


def load_results(results_path: str) -> dict:
    """加载 results.json，按 db_id 分组"""
    if not os.path.exists(results_path):
        print(f"文件不存在: {results_path}")
        return {}

    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    grouped = {}
    for item in data:
        db_id = item.get('db_id', 'unknown')
        instance_id = item.get('instance_id', '')
        sql = item.get('sql', '')

        if not sql:
            continue

        sql = clean_sql(sql)

        if db_id not in grouped:
            grouped[db_id] = {}

        grouped[db_id][instance_id] = sql

    return grouped


def main():
    script_dir = Path(__file__).parent
    db_dirs = ['db1', 'db2', 'db3', 'db4', 'db5']

    all_results = {}

    for i, db_dir in enumerate(db_dirs, 1):
        results_path = script_dir / db_dir / 'results.json'
        if not results_path.exists():
            print(f"跳过不存在的目录: {results_path}")
            continue

        print(f"处理 {results_path}...")
        grouped = load_results(str(results_path))

        for db_id, queries in grouped.items():
            sub_key = f"sub-database-{i}"
            if sub_key not in all_results:
                all_results[sub_key] = {}
            all_results[sub_key].update(queries)

    output_path = script_dir / 'pred.jsonl'
    with open(output_path, 'w', encoding='utf-8') as f:
        for sub_db, queries in all_results.items():
            line = json.dumps({sub_db: queries}, ensure_ascii=False)
            f.write(line + '\n')

    print(f"\n生成完成: {output_path}")
    print(f"总计 {len(all_results)} 个 sub-database")

    for sub_db, queries in all_results.items():
        print(f"  {sub_db}: {len(queries)} 条 SQL")


if __name__ == '__main__':
    main()
