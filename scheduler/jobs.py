# -*- coding: UTF-8 -*-
import sys
import os
import random
import hashlib
import requests
import time
import json



def scheduled_task_example(say):
    print(say)
    '''访问/token接口获取token'''
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6Ikh5cGVyaW9uIiwicm9sZSI6Imh5cGVyaW9uIiwiZXhwIjoxNzYyOTMwODg3fQ.cfzz5NG2vfCApkjvFIlv-7k2xjuDjwP1IkebJFgD7xg"
    }
    # 使用json参数发送JSON数据，而不是使用data参数发送表单数据
    token = requests.get('http://127.0.0.1:8188/check-token', headers=headers)

