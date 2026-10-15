# -*- coding: UTF-8 -*-
"""统一响应结构（平铺信封）— 开发纲领 §2 缺口5

锁定 ok()/ok_msg()/fail() 的信封形状，防回归：
    - 平铺展开 payload dict，保留前端已消费的 items/total/success/message 键；
    - 不引入嵌套 data 层（前端读取路径不变）；
    - fail() 与 ok() 对称（success: False）。
"""
from app.response import ErrorCode, fail, ok, ok_msg


def test_ok_spreads_dict_payload():
    """payload 为 dict 时平铺，items/total 保持顶层可读"""
    body = ok({'items': [1, 2], 'total': 2})
    assert body['code'] == 0
    assert body['success'] is True
    assert body['items'] == [1, 2]
    assert body['total'] == 2
    assert body['message'] == 'ok'
    assert 'data' not in body  # 不引入嵌套层


def test_ok_non_dict_payload_falls_back_to_data_key():
    """payload 非 dict（标量/列表）落到 data 键"""
    body = ok([1, 2, 3])
    assert body['data'] == [1, 2, 3]
    assert body['code'] == 0


def test_ok_msg_mutation_shape():
    """mutation 简写：code/success/message 三键"""
    body = ok_msg('更新成功')
    assert body == {'code': 0, 'success': True, 'message': '更新成功'}


def test_ok_msg_with_extra_keys():
    """ok_msg 透传额外键（如 output）"""
    body = ok_msg('安装成功', output='done')
    assert body['output'] == 'done'
    assert body['success'] is True


def test_fail_symmetric_with_ok():
    """fail 与 ok 对称：success=False + 平铺"""
    body = fail(ErrorCode.BAD_REQUEST, '参数错误')
    assert body == {'code': 40000, 'success': False, 'message': '参数错误'}
    body2 = fail(ErrorCode.INTERNAL, '失败', {'output': 'x'})
    assert body2['output'] == 'x'
    assert body2['success'] is False


def test_error_code_values():
    """错误码枚举：前3位对齐 HTTP 状态"""
    assert ErrorCode.BAD_REQUEST == 40000
    assert ErrorCode.NOT_FOUND == 40400
    assert ErrorCode.RATE_LIMITED == 42900
    assert ErrorCode.OK == 0
