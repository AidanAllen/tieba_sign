#!/usr/bin/env bash
# ============================
# 百度贴吧签到 — Linux 一键运行脚本
# 首次运行自动初始化：安装依赖 + Chromium 浏览器
# ============================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- 1. 检查 .env ----
if [ ! -f ".env" ]; then
    error ".env 文件不存在，请创建 .env 并配置 COOKIE"
    exit 1
fi

# 检查 COOKIE 是否已配置（非空且非默认占位）
if grep -q '^COOKIE=""' .env 2>/dev/null; then
    error ".env 中 COOKIE 为空，请填入百度贴吧 Cookie"
    exit 1
fi

# ---- 2. 检查 Python ----
if ! command -v python3 &>/dev/null; then
    error "未找到 python3，请先安装 Python 3.8+"
    exit 1
fi

# ---- 3. 初始化虚拟环境 / 依赖 ----
if [ ! -d ".venv" ]; then
    info "正在创建 Python 虚拟环境..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# 检查依赖是否已安装
if ! pip show -q requests 2>/dev/null; then
    info "正在安装 Python 依赖..."
    pip install -q -r requirements.txt
fi

# ---- 4. 安装 Playwright Chromium（已安装则自动跳过） ----
if ! pip show -q playwright 2>/dev/null; then
    info "正在安装 Playwright..."
    pip install -q playwright
fi
info "正在检查 Playwright Chromium 浏览器..."
python3 -m playwright install chromium

# ---- 5. 运行签到 ----
info "开始执行签到..."
python3 tieba_sign.py "$@"
