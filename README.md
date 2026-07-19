# 百度贴吧自动签到

基于 Playwright Chromium 的贴吧自动签到工具。通过 `.env` 统一配置，支持多线程并发、失败重试、代理池、企业微信通知，适合部署在服务器上定时运行。

---

## 目录

- [功能特性](#功能特性)
- [项目结构](#项目结构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [使用方式](#使用方式)
- [代理池配置](#代理池配置)
- [企业微信通知](#企业微信通知)
- [定时运行 (cron)](#定时运行-cron)
- [核心逻辑](#核心逻辑)
- [注意事项](#注意事项)
- [常见问题](#常见问题)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 多线程并发签到 | 默认 3 线程并发（`.env` 中通过 `THREADS` 调整） |
| 自动获取贴吧列表 | 自动分页抓取所有关注贴吧 |
| 页面加载重试 | 超时自动重试 1 次 |
| 签到失败重试 | 签到失败自动重试，间隔约 2 分钟 |
| 随机延迟 | 请求间随机延迟（`DELAY_MIN` ~ `DELAY_MAX`，默认 1~3 秒） |
| 每日防重复 | 签到成功后生成 `.lock` 文件，同一天内再次运行自动跳过 |
| 代理池支持 | 可选启用代理池，支持 HTTP/HTTPS/SOCKS，可按国家筛选 |
| Cookie 失效检测 | 自动检测登录态，Cookie 过期时提前终止并推送提醒 |
| 企业微信通知 | 签到完成或 Cookie 过期时通过 Webhook 推送到企业微信群 |
| JSON 统计输出 | 通过 `JSON_STATS` 配置路径，输出结构化签到结果 |
| 日志按日期拆分 | 每天独立日志文件，自动轮转 |
| 一键部署脚本 | `run.sh` 自动完成虚拟环境、依赖安装和 Chromium 初始化 |

---

## 项目结构

```
tieba_sign/
├── tieba_sign.py        # 主程序（纯 .env 配置，无命令行参数）
├── run.sh               # Linux 一键运行脚本（自动安装依赖 + 启动）
├── .env                 # 配置文件（必填：COOKIE；可选：WEBHOOK_URL 等）
├── .env.example         # 配置模板，复制为 .env 后编辑
├── requirements.txt     # Python 依赖（playwright + requests）
├── log/                 # 日志目录（自动创建）
│   └── tieba_sign_YYYY-MM-DD.log
├── .lock                # 签到日期锁（自动生成，当日防重复）
└── README.md
```

---

## 环境要求

- **Python**：3.8+
- **依赖**：`playwright`、`requests`

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置 `.env`

在项目目录创建 `.env` 文件（可复制 `.env.example` 后编辑）：

```bash
cp .env.example .env
```

最低配置只需填写 `COOKIE`：

```ini
COOKIE="BDUSS=xxx; STOKEN=yyy"
```

**获取 Cookie：**
1. 浏览器登录 [百度贴吧](https://tieba.baidu.com/)
2. 按 `F12` → **Application** → **Cookies** → `tieba.baidu.com`
3. 右键复制所有 Cookie 值，粘贴到 `COOKIE=""` 的引号内

> `WEBHOOK_URL` 为可选项，不配置则跳过企业微信通知。各可选配置项详见下文「[配置说明](#配置说明)」。

### 3. 运行

```bash
python3 tieba_sign.py
```

或使用一键脚本（推荐，可自动处理虚拟环境和依赖）：

```bash
bash run.sh
```

---

## 配置说明

所有配置均通过 `.env` 文件管理，**不支持命令行参数**。留空的配置项使用代码内默认值。

### 必填配置

| 变量 | 说明 |
|------|------|
| `COOKIE` | 百度贴吧登录 Cookie（BDUSS + STOKEN 等完整字符串） |

### 可选配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WEBHOOK_URL` | 空（不推送） | 企业微信机器人 Webhook URL |
| `LOG_DIR` | `log/` | 日志目录 |
| `THREADS` | `3` | 并发签到线程数（建议 2~5） |
| `RETRY` | `5` | 单个贴吧签到失败重试次数 |
| `DELAY_MIN` | `1.0` | 签到前最小随机延迟（秒） |
| `DELAY_MAX` | `3.0` | 签到前最大随机延迟（秒） |
| `JSON_STATS` | 空（不输出） | JSON 统计文件路径，如 `log/stats.json` |
| `QUIET` | `false` | 静默模式，`true` 时仅写入日志文件，不输出到控制台 |
| `PROXY_ENABLED` | `false` | 是否启用代理池 |

### 代理池相关配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXY_ENABLED` | `false` | 启用代理池（`true`/`false`） |
| `PROXY_API_URL` | `https://proxy.scdn.io/api/get_proxy.php` | 代理池 API 地址 |
| `PROXY_PROTOCOL` | `all` | 筛选协议：`http`/`https`/`socks4`/`socks5`/`all` |
| `PROXY_COUNTRY_CODE` | 空（不限） | 筛选国家代码，如 `CN`、`US`（ISO 3166-1） |

### 示例 `.env`

```ini
COOKIE="BDUSS=xxx; STOKEN=yyy"
WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"

THREADS=5
RETRY=3
DELAY_MIN=2.0
DELAY_MAX=5.0
QUIET=true
JSON_STATS=log/stats.json

PROXY_ENABLED=true
PROXY_PROTOCOL=https
PROXY_COUNTRY_CODE=CN
```

---

## 使用方式

```bash
# 直接运行（需自行安装依赖）
python3 tieba_sign.py

# 使用一键脚本（推荐，自动初始化）
bash run.sh
```

`run.sh` 自动完成以下步骤：
1. 检查 `.env` 是否存在且 `COOKIE` 已配置
2. 检查 Python 环境
3. 自动创建 Python 虚拟环境（`.venv/`）
4. 安装 `requirements.txt` 中的依赖
5. 安装 Playwright Chromium 浏览器（仅首次）
6. 执行签到

---

## 代理池配置

签到请求默认使用直连。如需通过代理 IP 降低触发验证码的风险，可在 `.env` 中启用代理池：

```ini
# 启用代理池
PROXY_ENABLED=true
# 代理池 API（默认值，可按需更换）
PROXY_API_URL=https://proxy.scdn.io/api/get_proxy.php
# 只使用 HTTPS 代理
PROXY_PROTOCOL=https
# 仅使用中国 IP
PROXY_COUNTRY_CODE=CN
```

代理池在每次启动 Chromium 时从 API 获取一个代理 IP，所有请求通过该代理发出。

---

## 企业微信通知

签到完成后推送结果到企业微信群。Cookie 过期时会发送**登录失效**提醒。

### 配置

在 `.env` 中设置 `WEBHOOK_URL`：

```ini
WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
```

### 推送内容

**正常签到完成：**

```
## 📊 百度贴吧自动签到
### 日期：2026-07-01
> **总计贴吧：** 85
> **签到成功：** 85
> **签到失败：** 0
```

**Cookie 已失效：**

```
## 📊 百度贴吧自动签到
### 日期：2026-07-01
> **通知：** 登录已失效，请重新登录
```

---

## 定时运行 (cron)

```bash
# 每天 9 点执行（使用一键脚本）
0 9 * * * cd /path/to/tieba_sign && bash run.sh

# 每天 9 点和 21 点，输出 JSON 统计
0 9,21 * * * cd /path/to/tieba_sign && python3 tieba_sign.py
```

> `run.sh` 日志写入文件，控制台输出由 `.env` 中 `QUIET` 控制。
> `run.sh` 中默认会生成 JSON 统计文件到 `log/` 目录。

---

## 核心逻辑

### 执行流程

```
启动
  │
  ├─ .lock 存在且日期为今天 → 已签到，跳过 → 退出(0)
  │
  ▼
加载 .env → 读取 COOKIE
  ├─ .env 不存在 → 退出(1)
  ├─ COOKIE 为空 → 退出(1)
  │
  ▼
启动 Chromium（无头）
  ├─ PROXY_ENABLED=true → 从代理池 API 获取代理 IP 并配置
  └─ PROXY_ENABLED=false → --no-proxy-server
  │
  ▼
注入 Cookie → 打开关注贴吧列表页
  ├─ 被重定向到登录页 → Cookie 过期 → 推送通知 → 退出(0)
  │
  ▼
分页获取所有关注贴吧（JS 解析 + 正则备用）
  │
  ▼
多线程并发签到（页面池固定，最多 3 页）
  │
  ├─ no=0         → 签到成功
  ├─ no=1101      → 今日已签到
  ├─ no=1010      → Cookie 失效，终止全部任务
  ├─ need vcode   → 冷却 30~60 秒重试
  └─ 其他错误     → 等待 ~2 分钟重试（最多 RETRY 次）
  │
  ▼
输出统计 / JSON / 企业微信通知
  │
  ├─ 写入 .lock → 下次运行跳过当天
  └─ 列表请求有超时 → 不写 .lock（次日重新获取完整列表）
```

### 函数说明

| 函数 | 说明 |
|------|------|
| `parse_cookie_string()` | 将 Cookie 字符串解析为 Playwright Cookie 格式 |
| `load_env()` | 解析 `.env` 文件 |
| `TiebaSigner._resolve_config()` | 合并 `.env` → 代码默认配置 |
| `TiebaSigner._load_cookie_str()` | 从 `self.env` 读取 COOKIE |
| `TiebaSigner._fetch_html()` | 页面加载，超时 120s，失败自动重试 1 次 |
| `TiebaSigner._fetch_api()` | 通过 Playwright API 发送签到请求（POST） |
| `TiebaSigner._launch_browser()` | 启动 Chromium（无头），注入 Cookie，可选配置代理 |
| `TiebaSigner._fetch_proxy()` | 从代理池 API 获取一个代理 IP |
| `TiebaSigner._get_followed_tiebas()` | 分页抓取关注贴吧，JS 解析 + 备用正则 |
| `TiebaSigner._sign_one()` | 单个贴吧签到，含随机延迟和失败重试 |
| `TiebaSigner._sign_all()` | 并发调度，固定页面池（最多 3 页） |
| `TiebaSigner._send_wechat()` | 企业微信通知（区分过期 / 正常） |
| `TiebaSigner._check_lock()` / `_write_lock()` | 读取/写入 `.lock` 文件，实现每日防重复 |

---

## 注意事项

1. **Cookie 有效期**：BDUSS 通常约 30 天，过期后需重新获取并更新 `.env`
2. **签到频率**：建议每天 1~2 次，频繁易触发验证码；`.lock` 机制保证每天最多签到 1 次
3. **线程数**：建议 `THREADS=2~5`，过高易触发百度反爬
4. **验证码**：触发后自动冷却 30~60 秒重试
5. **日志清理**：长期运行后建议定期清理 `log/` 目录
6. **代理池**：使用的第三方代理 API 地址可在 `.env` 中自行更换

---

## 常见问题

### Q: Cookie 在哪获取？
A: 浏览器 F12 → Application → Cookies → `tieba.baidu.com`，复制完整 Cookie 字符串填入 `.env` 的 `COOKIE=""`。

### Q: 签到全部失败？
A: Cookie 可能过期，重新获取后更新 `.env`；或检查 `.env` 格式是否正确（值不要多余空格）。

### Q: 总是触发验证码？
A: 调低 `THREADS`（如 2），增大 `DELAY_MIN`/`DELAY_MAX` 的随机间隔，或启用代理池。

### Q: 企业微信通知失败？
A: 检查 `.env` 中 `WEBHOOK_URL` 是否正确，以及网络能否访问 `qyapi.weixin.qq.com`。

### Q: 怎么在服务器上长期运行？
A: 配置好 `.env`，cron 定时调用 `bash run.sh` 即可。

### Q: `.lock` 文件是做什么的？
A: 签到成功后自动生成，记录当天的日期。同一天再次运行脚本会检测到 `.lock` 并直接跳过，避免重复签到。如需重新签到，删除 `.lock` 文件即可。

---

## License

MIT License
