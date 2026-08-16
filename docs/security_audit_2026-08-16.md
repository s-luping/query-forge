# QueryForge 安全审计报告

- **审计日期**: 2026-08-16
- **审计范围**: 后端全部路由/服务层、SQL 权限网关、加密模块、前端页面、脚本与配置
- **审计方法**: 人工代码审查（OWASP Top 10 / CWE Top 25 视角），静态走查，未做渗透测试
- **风险统计**: Critical 2 / High 4 / Medium 5 / Low 3

---

## 一、系统概览与信任边界

| 项目 | 内容 |
|---|---|
| 架构 | FastAPI 单体 + SQLite 双库（WAL）+ 前端静态页（无框架） |
| 认证 | JWT (HS256)，cookie 或 Bearer 双通道 |
| 敏感数据 | 用户密码、LLM API Key（Fernet 加密）、外部数据源密码（Fernet 加密）、业务 schema 元数据 |
| 信任边界 | 浏览器 → FastAPI（JWT）→ SQLite 主库/遥测库；管理员 → 外部数据库（同步连接器） |

## 二、STRIDE 摘要

| 威胁 | 位置 | 风险 | 现状 |
|---|---|---|---|
| Spoofing（仿冒） | JWT 签名密钥 | **Critical** | 后备密钥硬编码，配置缺失时可伪造任意用户 token |
| Tampering（篡改） | SQL 网关 | 低 | AST 解析 + 字段级权限，设计良好；但默认放行 |
| Repudiation（抵赖） | 审计日志 | 低 | 已有 log_audit + 遥测，覆盖可接受 |
| Info Disclosure（信息泄露） | 密码存储 | **Critical** | 明文存储；另脚本硬编码管理员密码 |
| DoS | 登录/LLM 接口 | 低 | slowapi 限速已覆盖主要入口 |
| Elevation of Priv | 注册/权限网关 | **High** | 开放注册即激活；网关默认 SELECT |

---

## 三、漏洞清单（按严重级别）

### 🔴 C-1 密码明文存储与比对 【Critical】

**位置**:
- `app/auth.py:52-53` — `User.password == password` 直接比对
- `app/routers/base_router.py:103` — 注册时 `password=password` 原样入库
- `app/routers/user_router.py:47,58` — 改密时明文比对、明文更新
- `models/user.py` — password 列存明文

**影响**: 拿到 `db/queryforge.db` 文件（或任意 SQL 注入/备份泄漏）即获得全部用户口令；口令复用会横向击穿其他系统。

**修复（改动点）**:
1. `requirements.txt` 加 `bcrypt`（或 `passlib[bcrypt]`）。
2. `models/user.py`：新增 `password_hash` 列（String(128)），保留旧 `password` 列做迁移。
3. `app/auth.py` 增加:
   ```python
   import bcrypt
   def hash_password(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
   def verify_password(p, h): 
       try: return bcrypt.checkpw(p.encode(), h.encode())
       except ValueError: return False
   ```
4. `authenticate_user` 改为：查用户 → `verify_password(password, user.password_hash)`。
5. `base_router.register` / `user_router.change_password` 写入 `password_hash=hash_password(...)`。
6. 一次性迁移脚本：遍历 users，`password_hash = hash_password(旧password)`，然后置空 `password` 列。
7. 顺带修复：改密成功后使旧 token 失效（JWT payload 加 `pwd_ts`，校验时比对）。

---

### 🔴 C-2 JWT 签名密钥与加密密钥同源，且有硬编码后备值 【Critical】

**位置**:
- `app/auth.py:11` — `_FALLBACK_SECRET_KEY = 'queryforge-fallback-secret-change-me'`
- `app/auth.py:15-28` — SECRET_KEY 从 `system_settings` 表读取（明文），读不到就用后备值
- `app/security/crypto.py:19-21` — Fernet 密钥由同一 SECRET_KEY 派生

**影响**:
- 后备路径：任何人可用公开的后备密钥伪造 admin token（`jwt.encode({"user_id":1,"username":"admin","role":"admin"}, ...)`）。
- 密钥同源：`queryforge.db` 文件一旦泄露，SECRET_KEY 明文在内 → 所有 LLM API Key、数据源密码全部可解密。

**修复（改动点）**:
1. `app/config.py` 增加:
   ```python
   import secrets
   SECRET_KEY = os.getenv('QUERYFORGE_SECRET_KEY', '')
   FERNET_KEY = os.getenv('QUERYFORGE_FERNET_KEY', '')
   ```
2. `_get_secret_key()` 删除 fallback 分支：读不到 env 又读不到配置时直接 `raise RuntimeError('SECRET_KEY 未配置，拒绝启动')`，绝不回落到硬编码值。
3. `crypto.py` 的 Fernet 密钥改从 `QUERYFORGE_FERNET_KEY`（Fernet 格式独立密钥）读取，与 JWT 密钥分离；轮换后旧密文已按现逻辑返回空串，兼容。
4. `.env.template` 补充两个变量及生成命令注释（`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`）。
5. 数据库 `system_settings` 中的 SECRET_KEY 行保留但不再作为首选来源（env 优先）。

---

### 🟠 H-1 脚本硬编码管理员密码 【High】

**位置**: `scripts/batch_generate.py:56` — `"password": "REDACTED"`

**修复**: 改为 `os.getenv('BATCH_DB_PASSWORD')`；该密码疑似真实口令，**建议立即轮换**；若仓库已推远端，密码已进入 git 历史，轮换是唯一补救。

---

### 🟠 H-2 Token 以 JS 写入 cookie，无 HttpOnly/Secure/SameSite 【High】

**位置**: `static/template/login.html:181` — `document.cookie = \`token=${data.access_token}; path=/;\``

**影响**: 任意 XSS（当前又没有 CSP）即可窃取 token；无 SameSite 也增加 CSRF 面。

**修复（改动点）**:
1. 后端 `/login`（`app/routers/base_router.py`）改为由服务器 Set-Cookie：
   ```python
   from fastapi.responses import JSONResponse
   resp = JSONResponse({"user_id": ..., "username": ..., "role": ...})
   resp.set_cookie("token", token, httponly=True, samesite="lax",
                   secure=(not DEBUG), max_age=60*expire_minutes, path="/")
   return resp
   ```
2. `login.html` 删除 JS 写 cookie，只处理跳转；`main.py:/logout` 的清除 cookie 加同样的 `httponly/samesite/secure` 属性（否则清不掉）。
3. 各页面读取 cookie 的逻辑可保留（读 cookie 名不受 HttpOnly 影响）。

---

### 🟠 H-3 开放注册即激活 【High】

**位置**: `app/routers/base_router.py:80-114` — `/register` 无需任何审批，`is_active=1` 直接可登录并使用 SQL 生成、schema 查询等全部用户权限。

**修复（改动点）**: 注册时 `is_active=0`，由管理员在用户管理页激活；或加邀请码字段。若业务确实需要开放注册，至少把注册接口的密码策略从 6 位统一到 `_validate_password_strength`（当前管理员改密走强策略、注册走弱策略，不一致）。

---

### 🟠 H-4 CORS 全通配 + 允许凭据 【High】

**位置**: `main.py:47-53` — `allow_origins=["*"], allow_credentials=True`

**修复（改动点））**: 收敛为白名单：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://10.0.0.207:8188", "http://localhost:8188"],  # 按实际访问地址配置，建议走 env
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

### 🟡 M-1 SQL 权限网关"默认放行" 【Medium】

**位置**: `services/sql/gateway.py:214` — `access = self._access_map.get(col_id, 'SELECT')`；`gateway.py:209-211` 未知字段直接跳过。

**影响**: 未配置权限的新字段、未纳管字段对普通用户默认可见，违背默认拒绝原则。

**修复（改动点）**: 非 admin 路径下：
- `_check_permissions` 中未知字段（`col_info is None`）改为记 warning 并拦截（或至少 `hit_sensitive` 打标）；
- `_access_map` 缺项时默认 `'NONE'`，需要显式授权才可见。改完跑一遍现有用户查询回归，确认权限数据是否已配全。

---

### 🟡 M-2 错误响应泄漏内部异常 【Medium】

**位置**: `app/routers/base_router.py:76`、`chat_to_sql_router.py:204`、`system_router.py:184` 等多处 `detail=f"...{str(e)}"`。

**影响**: 堆栈/路径/SQL 报错原文直达客户端，辅助攻击者侦察。

**修复（改动点）**: 统一 `logger.exception(e)` + `raise HTTPException(500, "服务器内部错误，请稍后重试")`；可在全局 exception handler 中统一处理。

---

### 🟡 M-3 Swagger/ReDoc 生产暴露 【Medium】

**位置**: `main.py:43` — `docs_url="/docs", redoc_url="/redoc"`

**修复（改动点））**: `docs_url="/docs" if DEBUG else None, redoc_url=None`（`app/config.py` 已有 DEBUG 变量，直接复用）。

---

### 🟡 M-4 缺失安全响应头 【Medium】

**位置**: `main.py`（无任何安全头中间件）

**修复（改动点））: 在 `main.py` 加一个轻量中间件：
```python
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # CSP 按前端实际内联脚本情况放宽，先上最小集
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
    return resp
```
注意：前端页面大量内联 `<script>`，上严格 CSP 前需先评估，可分两步走。

---

### 🟡 M-5 改密后旧 token 不失效 【Medium】

**位置**: `user_router.change_password` 成功后无撤销动作；token 有效期默认 3 天（`app/auth.py:12`）。

**修复（改动点）): JWT payload 加 `pwd_ts`（改密时间戳），`get_current_user` 校验 `payload['pwd_ts'] == user.pwd_ts`，不一致即 401。配合 C-1 迁移时在 User 表加一列即可。

---

### ⚪ 低危（列出供后续处理）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| L-1 | 裸 `except:` 吞异常 | `main.py:72`、`app/auth.py:26,43` | 至少 `except Exception as e: logger.debug(e)` |
| L-2 | `validation_cache` 无上限增长 | `chat_to_sql_router.py:48` | 加容量上限或 TTL 淘汰 |
| L-3 | 行级过滤表达式直接拼入 AST | `gateway.py:306` | 仅管理员可配置，风险可控；建议对 filter_expr 做白名单校验（仅允许 `col op value AND/OR`） |

---

## 四、做得好的地方（保持）

| 控制项 | 位置 | 评价 |
|---|---|---|
| API Key Fernet 加密 + `enc::` 前缀 + 列表脱敏 | `app/security/crypto.py`、`llm_router.py:267` | ✔ |
| 数据源密码加密存储 + 列表不回传 | `sync_router.py:118` | ✔ |
| 登录/注册限速 2/min | `base_router.py:42,79` | ✔ |
| 管理端接口 admin 校验完整（数据源/系统设置） | `sync_router.py`、`system_router.py` | ✔ |
| SQL AST 权限网关（字段级 SELECT/FILTER/NONE + 行级注入） | `services/sql/gateway.py` | 设计优于多数同类实现，仅需修默认策略 |
| 全部内部查询走 ORM/参数化，未发现 SQL 注入拼接 | 全局 grep | ✔ |

## 五、修复优先级与验证方式

| 优先级 | 项 | 验证 |
|---|---|---|
| ★★★ 本周 | C-1 密码哈希、C-2 密钥管理、H-1 轮换 REDACTED | 登录/改密回归；无 SECRET_KEY 环境变量时进程拒绝启动 |
| ★★☆ 两周内 | H-2 HttpOnly cookie、H-3 注册审批、H-4 CORS 白名单 | 浏览器 DevTools 确认 cookie 标志；新注册账号无法直接登录 |
| ★☆☆ 下个迭代 | M-1 ~ M-5 | M-1 用无权限字段构造查询应被拦；`/docs` 生产环境 404 |
| 备忘 | L-1 ~ L-3 | 代码评审时顺手处理 |

## 六、部署面补充建议

- `docker-compose.yml` 检查 8188 端口映射范围，内网工具建议绑定特定网段而非 `0.0.0.0` 全暴露。
- `db/*.db` 已在 `.gitignore`（✔），但注意运行机上的定时备份文件也要同样管控权限。
- 上生产前置反向代理（nginx）终结 TLS，开启 HSTS。
