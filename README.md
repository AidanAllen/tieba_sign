# 百度贴吧自动签到

基于 Playwright Chromium 的多线程自动签到工具。配置统一存放 `.env`，适合定时任务。

---

## 目录

- [功能特性](#功能特性)
- [项目结构](#项目结构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [企业微信通知](#企业微信通知)
- [定时运行](#定时运行-cron)
- [核心逻辑](#核心逻辑)
- [注意事项](#注意事项)
- [常见问题](#常见问题)

---

## 功能特性

| 功能 | 说明 |
|------|------|
| 多线程签到 | 默认 3 线程并发，可自定义 |
| 自动获取贴吧 | 自动分页抓取所有关注贴吧 |
| 失败重试 | 失败自动重试，间隔约 2 分钟 |
| 随机延迟 | 请求间随机延迟 1~3 秒 |
| 日志按日期拆分 | 每天独立日志文件 |
| 企业微信通知 | Cookie 过期或签到完成时推送 |
| Cookie 失效检测 | 自动检测并提前终止，推送提醒 |
| .env 配置 | Cookie 和 Webhook 统一管理 |
| JSON 统计输出 | `--json-stats` 输出结构化结果 |

---

## 项目结构

```
tieba_sign/
├── tieba_sign.py        # 主程序
├── .env                 # 配置文件（Cookie + Webhook）
├── requirements.txt     # Python 依赖
├── log/                 # 日志目录（自动创建）
│   └── tieba_sign_YYYY-MM-DD.log
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

### 2. 配置 .env

在项目目录创建 `.env` 文件（已提供模板）：

```ini
COOKIE="BDUSS=xxx; STOKEN=yyy"
WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
```

**获取 Cookie：**
1. 浏览器登录 [百度贴吧](https://tieba.baidu.com/)
2. 按 `F12` → **Application** → **Cookies** → `tieba.baidu.com`
3. 右键复制所有 Cookie 值，粘贴到 `COOKIE=""` 的引号内

> `WEBHOOK_URL` 为可选项，不配置则跳过企业微信通知。

### 3. 运行

```bash
python3 tieba_sign.py
```

---

## 使用方式

### 命令行参数

```
python3 tieba_sign.py [选项]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--log-dir` | `log/` | 日志目录 |
| `--threads` | `3` | 并发线程数 |
| `--retry` | `5` | 失败重试次数 |
| `--delay-min` | `1` | 签到前最小随机延迟（秒） |
| `--delay-max` | `3` | 签到前最大随机延迟（秒） |
| `--json-stats` | 不输出 | JSON 统计文件路径 |
| `--quiet` | 否 | 静默模式，仅写入日志文件 |

### 示例

```bash
# 基本用法
python3 tieba_sign.py

# 5 线程 + 静默模式 + JSON 输出（cron 推荐）
python3 tieba_sign.py --threads 5 --quiet --json-stats /tmp/tieba_result.json

# 指定日志目录
python3 tieba_sign.py --log-dir /var/log/tieba
```

---

## 企业微信通知

签到完成后推送结果。Cookie 过期时会发送**登录失效**提醒。

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
# 每天 9 点执行
0 9 * * * cd /path/to/tieba_sign && python3 tieba_sign.py --quiet

# 每天 9 点和 21 点，输出 JSON
0 9,21 * * * cd /path/to/tieba_sign && python3 tieba_sign.py --quiet --json-stats /tmp/tieba_result.json
```

---

## 核心逻辑

### 执行流程

```
启动
  │
  ▼
加载 .env → 读取 COOKIE
  │
  ▼
启动 Chromium → 注入 Cookie
  │
  ├─ 被重定向到登录页 → Cookie 过期，推送通知 → 退出(0)
  │
  ▼
获取关注贴吧列表（分页）
  │
  ▼
多线程并发签到
  │
  ├─ no=0         → 签到成功
  ├─ no=1101      → 今日已签到
  ├─ no=1010      → Cookie 失效，终止全部任务
  ├─ need vcode   → 冷却 30~60 秒重试
  └─ 其他错误     → 等待 ~2 分钟重试（最多 5 次）
  │
  ▼
输出统计 / JSON / 企业微信通知
```

### 函数说明

| 函数 | 说明 |
|------|------|
| `load_env()` | 解析 `.env` 文件 |
| `_load_cookie_str()` | 从 `self.env` 读取 COOKIE |
| `_get_followed_tiebas()` | 分页抓取关注贴吧，JS 解析 + 备用正则 |
| `_sign_one()` | 单个贴吧签到，含随机延迟和失败重试 |
| `_sign_all()` | 并发调度，固定页面池 |
| `_send_wechat()` | 企业微信通知（区分过期 / 正常） |

---

## 注意事项

1. **Cookie 有效期**：BDUSS 通常约 30 天，过期后需重新获取并更新 `.env`
2. **签到频率**：建议每天 1~2 次，频繁易触发验证码
3. **线程数**：建议 2~5，过高易触发百度反爬
4. **验证码**：触发后自动冷却 30~60 秒重试
5. **日志清理**：长期运行后建议定期清理 `log/` 目录

---

## 常见问题

### Q: Cookie 在哪获取？
A: 浏览器 F12 → Application → Cookies → `tieba.baidu.com`，复制完整 Cookie 字符串填入 `.env` 的 `COOKIE=""`。

### Q: 签到全部失败？
A: Cookie 可能过期，重新获取后更新 `.env`；或检查 `.env` 格式是否正确（值不要多余空格）。

### Q: 总是触发验证码？
A: 调低 `--threads` 到 2，或增大 `--delay-min/max` 的随机间隔。

### Q: 企业微信通知失败？
A: 检查 `.env` 中 `WEBHOOK_URL` 是否正确，以及网络能否访问 `qyapi.weixin.qq.com`。

### Q: 怎么在服务器上长期运行？
A: 配置好 `.env`，cron 定时调用 `python3 tieba_sign.py --quiet` 即可。

---

## License

MIT License
