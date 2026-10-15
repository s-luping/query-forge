# -*- coding: UTF-8 -*-
"""字段敏感等级自动分类测试 — services/sync_classify.py"""
from services.sync_classify import classify_batch, classify_column


def test_confidential():
    assert classify_column('password') == 'confidential'
    assert classify_column('user_password_hash') == 'confidential'
    assert classify_column('api_key') == 'confidential'
    assert classify_column('id_card_no') == 'confidential'


def test_sensitive():
    assert classify_column('phone') == 'sensitive'
    assert classify_column('mobile_number') == 'sensitive'
    assert classify_column('email_addr') == 'sensitive'
    assert classify_column('home_address') == 'sensitive'
    assert classify_column('salary') == 'sensitive'


def test_internal():
    assert classify_column('order_status') == 'internal'
    assert classify_column('record_type') == 'internal'
    assert classify_column('is_deleted') == 'internal'


def test_public():
    assert classify_column('product_name') == 'public'
    assert classify_column('amount') == 'public'
    assert classify_column('') == 'public'


def test_case_insensitive():
    assert classify_column('PassWord') == 'confidential'


def test_batch():
    result = classify_batch(['password', 'foo'])
    assert result == {'password': 'confidential', 'foo': 'public'}
