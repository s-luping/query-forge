from slowapi import Limiter
from slowapi.util import get_remote_address
# 1. 创建 Limiter 实例
limiter = Limiter(key_func=get_remote_address)