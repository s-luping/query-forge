# -*- coding: UTF-8 -*-
"""定时任务处理器注册中心 — 页面动态任务的可用处理器白名单

设计（参考 XXL-JOB 的 JobHandler 注册模式）：
    - 所有可被定时任务调用的函数必须在 JOB_HANDLERS 注册，
      页面「新增任务」的处理器下拉框即来源于此。
    - 每个处理器声明参数 schema（类型/默认值/说明），新增任务时
      前端按 schema 生成参数表单提示，后端按 schema 校验入参。
    - 任务定义（scheduler_jobs.handler）只存注册名，函数本体由本模块解析，
      避免把可调用对象序列化进数据库。

新增处理器步骤：
    1. 在 scheduler/jobs/ 下实现任务函数（返回 dict 作为结果摘要）
    2. 在下方 JOB_HANDLERS 注册：key / 函数 / 中文名 / 描述 / 参数 schema
"""
from typing import Any, Dict

from scheduler.jobs.retention import (
    cleanup_logs_db,
    cleanup_main_db,
    cleanup_telemetry,
    wal_checkpoint,
)
from scheduler.jobs.schema_sync import run_scheduled_syncs
from scheduler.jobs.usage_stats import aggregate_usage_stats
from scheduler.jobs.vector_index import rebuild_vector_index

# 参数 schema 字段：type(int/str/bool) / default / required / desc
_JOB_HANDLER_DEFS = [
    {
        'key': 'aggregate_usage',
        'func': aggregate_usage_stats,
        'label': 'LLM 用量聚合',
        'description': '按 天×用户×模型 聚合遥测库调用记录到 llm_usage_stats（幂等覆盖）',
        'params': [
            {'key': 'days_back', 'type': 'int', 'default': 7, 'required': False,
             'desc': '向前回溯的天数'},
        ],
    },
    {
        'key': 'cleanup_telemetry',
        'func': cleanup_telemetry,
        'label': '遥测数据清理',
        'description': '清理遥测库过期的 LLM 调用记录',
        'params': [
            {'key': 'retention_days', 'type': 'int', 'default': 90, 'required': False,
             'desc': '保留天数'},
        ],
    },
    {
        'key': 'cleanup_logs_db',
        'func': cleanup_logs_db,
        'label': '日志库清理',
        'description': '清理日志库过期数据（审计日志 / 同步历史 / 任务执行日志）',
        'params': [
            {'key': 'audit_retention_days', 'type': 'int', 'default': 90, 'required': False,
             'desc': '审计日志保留天数'},
            {'key': 'sync_retention_days', 'type': 'int', 'default': 90, 'required': False,
             'desc': '同步历史保留天数'},
        ],
    },
    {
        'key': 'cleanup_main_db',
        'func': cleanup_main_db,
        'label': '主库数据清理',
        'description': '清理主库过期的查询结果 JSON',
        'params': [
            {'key': 'result_retention_days', 'type': 'int', 'default': 30, 'required': False,
             'desc': '查询结果保留天数'},
        ],
    },
    {
        'key': 'wal_checkpoint',
        'func': wal_checkpoint,
        'label': 'WAL 日志回收',
        'description': '对 SQLite 主库执行 WAL checkpoint，回收日志文件空间',
        'params': [],
    },
    {
        'key': 'run_scheduled_syncs',
        'func': run_scheduled_syncs,
        'label': '同步任务调度巡检',
        'description': '巡检元数据同步任务并执行到期的同步（同步任务自身的间隔配置由此驱动）',
        'params': [],
    },
    {
        'key': 'rebuild_vector_index',
        'func': rebuild_vector_index,
        'label': '向量索引重建',
        'description': '按需重建全库向量索引：仅 stale/error/缺失 时构建（幂等），导入/同步只标记过期不再自动构建',
        'params': [
            {'key': 'force', 'type': 'bool', 'default': False, 'required': False,
             'desc': '强制重建（即使索引当前为 ready）'},
        ],
    },
]

JOB_HANDLERS: Dict[str, Dict[str, Any]] = {d['key']: d for d in _JOB_HANDLER_DEFS}


def list_handlers() -> list:
    """处理器列表（供前端下拉框与参数提示）"""
    return [
        {
            'key': d['key'],
            'label': d['label'],
            'description': d['description'],
            'params': d['params'],
        }
        for d in _JOB_HANDLER_DEFS
    ]


def get_handler_def(handler: str) -> Dict[str, Any]:
    return JOB_HANDLERS.get(handler)


def validate_params(handler: str, params: dict) -> dict:
    """按处理器 schema 校验并规范化参数 — 非法值抛 ValueError

    只接受 schema 中声明的键；int/bool 做类型转换；未传的必填项报错，
    未传的可选项回填默认值。
    """
    handler_def = get_handler_def(handler)
    if handler_def is None:
        raise ValueError(f'未注册的处理器: {handler}')
    schema = handler_def['params']
    params = params or {}
    if not isinstance(params, dict):
        raise ValueError('params 必须是 JSON 对象')
    unknown = set(params) - {p['key'] for p in schema}
    if unknown:
        raise ValueError(f'处理器 {handler} 不支持参数: {", ".join(sorted(unknown))}')

    normalized = {}
    for p in schema:
        key, ptype = p['key'], p['type']
        raw = params.get(key, None)
        if raw is None or raw == '':
            if p.get('required'):
                raise ValueError(f'缺少必填参数: {key}')
            normalized[key] = p['default']
            continue
        try:
            if ptype == 'int':
                normalized[key] = int(raw)
            elif ptype == 'bool':
                if isinstance(raw, str):
                    normalized[key] = raw.strip().lower() in ('1', 'true', 'yes', 'on')
                else:
                    normalized[key] = bool(raw)
            else:
                normalized[key] = str(raw)
        except (TypeError, ValueError):
            raise ValueError(f'参数 {key} 类型错误，应为 {ptype}')
    return normalized
