#!/usr/bin/env python3
"""
百度贴吧自动签到工具 — Chromium 浏览器版
配置统一存放 .env，无额外命令行参数依赖。
"""

import os
import re
import sys
import time
import json
import random
import asyncio
import logging
import requests
from datetime import datetime
from urllib.parse import unquote

from playwright.async_api import async_playwright

PAGE_URL = "https://tieba.baidu.com/f/like/mylike?&pn={}"
SIGN_URL = "https://tieba.baidu.com/sign/add"
RE_KW = re.compile(r'href="/f\?kw=([^"&]+)"')

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lock")

# 默认配置（.env 中留空则使用此值）
_DEFAULTS = {
    "log_dir": "",
    "threads": 3,
    "retry": 5,
    "delay_min": 1.0,
    "delay_max": 3.0,
    "json_stats": "",
    "quiet": False,
    "proxy_enabled": False,
    "proxy_api_url": "https://proxy.scdn.io/api/get_proxy.php",
    "proxy_protocol": "all",
    "proxy_country_code": "",
}

# .env 键名 → 内部配置键名 + 类型转换器
_ENV_MAP = {
    "LOG_DIR": ("log_dir", str),
    "THREADS": ("threads", int),
    "RETRY": ("retry", int),
    "DELAY_MIN": ("delay_min", float),
    "DELAY_MAX": ("delay_max", float),
    "JSON_STATS": ("json_stats", str),
    "QUIET": ("quiet", bool),
    "PROXY_ENABLED": ("proxy_enabled", bool),
    "PROXY_API_URL": ("proxy_api_url", str),
    "PROXY_PROTOCOL": ("proxy_protocol", str),
    "PROXY_COUNTRY_CODE": ("proxy_country_code", str),
}


def parse_cookie_string(cookie_str: str) -> list[dict]:
    """将 Cookie 字符串解析为 Playwright cookie 格式"""
    cookies = []
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".baidu.com",
            "path": "/",
        })
    return cookies


def load_env() -> dict[str, str]:
    """解析脚本目录下的 .env 文件，不存在时返回空 dict"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return {}
    env = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


def _parse_bool(value: str) -> bool:
    return value.lower() in ("true", "1", "yes")


class TiebaSigner:
    """贴吧签到器 — 基于 Playwright Chromium"""

    def __init__(self):
        self.env = load_env()
        self.cfg = self._resolve_config()
        self.logger = self._setup_logger()
        self.total = 0
        self.success = 0
        self.fail_list: list[str] = []
        self._cookie_expired = asyncio.Event()
        self._list_timeout = False

    def _resolve_config(self) -> dict:
        """合并 .env → 默认值，.env 中配置的值会覆盖代码默认值"""
        cfg = dict(_DEFAULTS)
        for env_key, (cfg_key, caster) in _ENV_MAP.items():
            raw = self.env.get(env_key)
            if raw == "" or raw is None:
                continue
            try:
                cfg[cfg_key] = caster(raw) if caster is not bool else _parse_bool(raw)
            except (ValueError, TypeError):
                continue
        return cfg

    # ====================== 日志 ======================

    def _setup_logger(self):
        log_dir = self.cfg["log_dir"] or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "log"
        )
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"tieba_sign_{datetime.now():%Y-%m-%d}.log")
        logger = logging.getLogger("tieba_sign")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        logger.addHandler(logging.FileHandler(log_file, encoding="utf-8"))
        logger.addHandler(logging.StreamHandler())
        if self.cfg["quiet"]:
            for h in logger.handlers[:]:
                if isinstance(h, logging.StreamHandler):
                    logger.removeHandler(h)
        return logger

    # ====================== Cookie 加载 ======================

    def _load_cookie_str(self) -> str | None:
        cookie = self.env.get("COOKIE", "").strip()
        if cookie:
            self.logger.info("✅ 从 .env 加载 Cookie")
            return cookie
        self.logger.error("❌ .env 中未配置 COOKIE")
        return None

    # ====================== 浏览器操作 ======================

    async def _fetch_html(self, page, url: str) -> str:
        for attempt in range(1, 3):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                if "passport.baidu.com" in page.url:
                    self._cookie_expired.set()
                    self.logger.error("❌ Cookie 已失效，被重定向到登录页")
                    return ""
                try:
                    await page.wait_for_function(
                        "document.querySelector('a[href*=\"/f?kw=\"]') "
                        "|| document.querySelector('a[href*=\"mylike?&pn=\"]') "
                        "|| document.body.innerText.includes('尾页') "
                        "|| document.body.innerText.includes('下一页')",
                        timeout=30000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)
                return await page.content()
            except Exception as e:
                self.logger.warning(f"❌ 页面加载失败（第 {attempt} 次）：{url[:60]} - {e}")
                self._list_timeout = True
                if attempt < 2:
                    wait = random.randint(5, 15)
                    self.logger.info(f"⏳ 等待 {wait} 秒后重试...")
                    await asyncio.sleep(wait)
        return ""

    async def _fetch_api(self, page, url: str, data: dict = None) -> dict:
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = await page.request.post(url, form=data, headers=headers)
            return await resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def _launch_browser(self, pw, cookies):
        self.logger.info('🚀 正在启动 Chromium...')
        proxy_addr = self._fetch_proxy()
        launch_args = ['--no-sandbox', '--disable-setuid-sandbox']
        new_context_kw = {}
        if proxy_addr:
            new_context_kw['proxy'] = {'server': f'http://{proxy_addr}'}
            self.logger.info(f'🌐 Chromium 已配置代理 {proxy_addr}')
        else:
            launch_args.append('--no-proxy-server')

        browser = await pw.chromium.launch(
            headless=True,
            args=launch_args,
        )
        context = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/149.0.0.0 Safari/537.36'
            ),
            locale='zh-CN',
            **new_context_kw,
        )
        await context.add_cookies(cookies)
        page = await context.new_page()
        self.logger.info('✅ Chromium 启动完成，Cookie 已注入')
        return browser, context, page

    # ====================== 代理池 ======================

    def _fetch_proxy(self) -> str | None:
        '''从代理池 API 获取一个代理 IP，返回 ip:port 或 None'''
        if not self.cfg.get('proxy_enabled'):
            return None
        api_url = self.cfg['proxy_api_url']
        protocol = self.cfg['proxy_protocol']
        params = {'protocol': protocol, 'count': 1}
        country_code = self.cfg.get('proxy_country_code', '')
        if country_code:
            params['country_code'] = country_code
        try:
            resp = requests.get(api_url, params=params, timeout=10)
            data = resp.json()
            if data.get('code') == 200:
                proxies = data.get('data', {}).get('proxies', [])
                if proxies:
                    proxy = proxies[0]
                    self.logger.info(f'🌐 从代理池获取代理：{proxy}（协议筛选：{protocol}）')
                    return proxy
            self.logger.warning('⚠️ 代理池返回异常：' + str(data.get('message', data)))
        except Exception as e:
            self.logger.warning('⚠️ 获取代理失败：' + str(e))
        return None

    # ====================== 获取贴吧列表 ======================

    async def _get_followed_tiebas(self, page) -> list[str]:
        self.logger.info("📋 正在获取关注贴吧列表...")
        self.logger.info("-" * 60)
        tiebas: set[str] = set()
        total_pages: int | None = None
        pn = 1

        while total_pages is None or pn <= total_pages:
            if self._cookie_expired.is_set():
                break

            url = PAGE_URL.format(pn)
            self.logger.info(f"📄 正在打开第 {pn} 页...")
            html = await self._fetch_html(page, url)
            if not html:
                pn += 1
                await asyncio.sleep(0.5)
                continue

            if total_pages is None:
                total_pages = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href*="mylike?&pn="]');
                    let max = 1;
                    links.forEach(a => {
                        const m = a.href.match(/pn=(\\d+)/);
                        if (m) max = Math.max(max, parseInt(m[1]));
                    });
                    return max;
                }""")
                self.logger.info(f"📄 共 {total_pages} 页")

            names = await page.evaluate("""() => {
                const items = [];
                document.querySelectorAll('a[href*="/f?kw="]').forEach(a => {
                    if (a.href.includes('mylike')) return;
                    const name = a.textContent.trim();
                    if (name && !name.includes('首页') && !name.includes('上一页')
                        && !name.includes('下一页') && !name.includes('尾页')) {
                        items.push(name);
                    }
                });
                return items;
            }""")
            if not names:
                html = await page.content()
                kws = RE_KW.findall(html)
                if kws:
                    names = [unquote(kw) for kw in kws]

            if names:
                tiebas.update(n.strip() for n in names if n.strip())
                self.logger.info(f"📄 第 {pn}/{total_pages} 页 → {len(names)} 个")
            else:
                self.logger.info(f"📄 第 {pn}/{total_pages} 页无贴吧")

            pn += 1
            await asyncio.sleep(0.3)

        self.total = len(tiebas)
        tieba_list = sorted(tiebas)
        self.logger.info("-" * 60)
        self.logger.info(f"✅ 共获取到 {self.total} 个关注贴吧")
        if tieba_list:
            self.logger.info(f"📝 {', '.join(tieba_list[:10])}")
            if len(tieba_list) > 10:
                self.logger.info(f"   ... 以及另外 {len(tieba_list) - 10} 个")
        return tieba_list

    # ====================== 签到 ======================

    async def _sign_one(self, page, name: str, delay: tuple[float, float], retry: int):
        if self._cookie_expired.is_set():
            return

        await asyncio.sleep(random.uniform(*delay))

        for attempt in range(1, retry + 1):
            if self._cookie_expired.is_set():
                return

            result = await self._fetch_api(
                page, SIGN_URL, data={"ie": "utf-8", "kw": name}
            )
            no = result.get("no")

            if no == 0 or no == 1101:
                self.success += 1
                tag = "签到成功" if no == 0 else "今日已签到"
                self.logger.info(f"✅ [{name}] {tag}")
                return

            if no == 1010:
                self._cookie_expired.set()
                self.logger.error(f"❌ [{name}] Cookie 已失效")
                return

            err = result.get("error", "")

            if "error" in result and not no:
                self.logger.warning(f"⚠️ [{name}] 请求失败：{err}")
                await self._wait_retry(name, attempt, retry)
                continue

            if err == "need vcode":
                self.logger.warning(f"🔒 [{name}] 第 {attempt}/{retry} 次触发验证码")
                if attempt < retry:
                    await asyncio.sleep(random.randint(30, 60))
                    continue

            self.logger.warning(
                f"⚠️ [{name}] 第 {attempt}/{retry} 次失败：{err or '未知错误'}"
            )
            await self._wait_retry(name, attempt, retry)

        self.fail_list.append(name)
        self.logger.error(f"❌ [{name}] 签到彻底失败（{retry} 次）")

    async def _wait_retry(self, name: str, attempt: int, retry: int):
        if attempt < retry:
            wait = 120 + random.randint(-10, 10)
            self.logger.info(f"⏳ [{name}] 等待 {wait} 秒后重试...")
            await asyncio.sleep(wait)

    async def _sign_all(self, context, tiebas: list[str]):
        self.logger.info(f"🚀 开始签到（{self.cfg['threads']} 页并发）")
        self.logger.info("=" * 55)
        delay = (self.cfg["delay_min"], self.cfg["delay_max"])
        n_pages = min(self.cfg["threads"], len(tiebas), 3)
        sign_pages = [await context.new_page() for _ in range(n_pages)] if n_pages > 0 else []
        sem = asyncio.Semaphore(max(len(sign_pages), 1))

        async def _sign_wrapper(name, idx):
            if self._cookie_expired.is_set():
                return
            async with sem:
                await self._sign_one(sign_pages[idx % len(sign_pages)], name, delay, self.cfg["retry"])

        tasks = [_sign_wrapper(tb, i) for i, tb in enumerate(tiebas)]
        await asyncio.gather(*tasks)

        for p in sign_pages:
            await p.close()

    # ====================== 统计输出 ======================

    def _print_banner(self):
        self.logger.info(
            f"\n╔══════════════════════════════════════════╗\n"
            f"║   🏠 百度贴吧自动签到 (Chromium)         ║\n"
            f"║   📅 {datetime.now():%Y-%m-%d %H:%M:%S}                 ║\n"
            f"║   🧵 {self.cfg['threads']} 线程   🔄 {self.cfg['retry']} 次重试                ║\n"
            f"╚══════════════════════════════════════════╝"
        )

    def _print_stats(self, elapsed: int):
        fail_n = len(self.fail_list)
        self.logger.info("=" * 55)
        self.logger.info(
            f"📊 总计 {self.total} | ✅ {self.success} | ❌ {fail_n} | ⏱️  {elapsed // 60}分{elapsed % 60}秒"
        )
        if self.fail_list:
            self.logger.info("❌ 失败：" + ", ".join(self.fail_list))
        self.logger.info("🎉 完成")

    def _write_json_stats(self, elapsed: int):
        if not self.cfg["json_stats"]:
            return
        fail_n = len(self.fail_list)
        stats = {
            "date": f"{datetime.now():%Y-%m-%d}",
            "timestamp": datetime.now().isoformat(),
            "total": self.total,
            "success": self.success,
            "fail": fail_n,
            "fail_list": self.fail_list,
            "cookie_expired": self._cookie_expired.is_set(),
            "elapsed_seconds": elapsed,
        }
        with open(self.cfg["json_stats"], "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    # ====================== 企业微信通知 ======================

    def _send_wechat(self):
        url = self.env.get("WEBHOOK_URL", "").strip()
        if not url:
            self.logger.info("ℹ️  .env 中未配置 WEBHOOK_URL，跳过通知")
            return

        if self._cookie_expired.is_set():
            content = (
                f"## 📊 百度贴吧自动签到\n"
                f"### 日期：{datetime.now():%Y-%m-%d}\n"
                f"> **通知：** 登录已失效，请重新登录"
            )
        else:
            fail_num = len(self.fail_list)
            fail_section = (
                f"\n>### ❌ 失败列表\n>{chr(10).join(f'- {n}' for n in self.fail_list)}\n>"
                if fail_num else ""
            )
            content = (
                f"## 📊 百度贴吧自动签到\n"
                f"### 日期：{datetime.now():%Y-%m-%d}\n"
                f"> **总计贴吧：** {self.total}\n"
                f"> **签到成功：** {self.success}\n"
                f"> **签到失败：** {fail_num}\n"
                f"{fail_section}"
            )

        try:
            resp = requests.post(
                url,
                json={"msgtype": "markdown", "markdown": {"content": content}},
                timeout=10,
            )
            if resp.json().get("errcode") == 0:
                self.logger.info("✅ 企业微信通知发送成功")
                self._write_lock()
            else:
                self.logger.warning(f"⚠️  通知返回异常：{resp.json()}")
        except Exception as e:
            self.logger.error(f"❌ 企业微信通知发送失败：{e}")

    # ====================== 主流程 ======================

    def _check_lock(self) -> bool:
        """检查 .lock 文件，如果日期是今天则返回 True"""
        if not os.path.exists(LOCK_FILE):
            return False
        try:
            with open(LOCK_FILE) as f:
                locked_date = f.read().strip()
            return locked_date == datetime.now().strftime("%Y-%m-%d")
        except Exception:
            return False

    def _write_lock(self):
        """写入今天的日期到 .lock 文件"""
        if self._list_timeout:
            self.logger.info("⏳ 列表请求存在超时，跳过生成 .lock，下次可继续获取完整列表")
            return
        try:
            with open(LOCK_FILE, "w") as f:
                f.write(datetime.now().strftime("%Y-%m-%d"))
        except Exception as e:
            self.logger.warning(f"⚠️ .lock 写入失败：{e}")

    async def _run_async(self):
        start = time.time()
        self._print_banner()

        if self._check_lock():
            self.logger.info("⏭️  今天已签到完成，跳过")
            sys.exit(0)

        if not self.env:
            self.logger.error("🚫 .env 文件不存在，请创建 .env 并配置 COOKIE")
            sys.exit(1)

        cookie_str = self._load_cookie_str()
        if not cookie_str:
            self.logger.error("🚫 无法加载 Cookie，终止")
            sys.exit(1)

        cookies = parse_cookie_string(cookie_str)

        async with async_playwright() as pw:
            browser, context, page = await self._launch_browser(pw, cookies)

            tiebas = await self._get_followed_tiebas(page)
            if self._cookie_expired.is_set():
                self.logger.error("🚫 Cookie 已失效，终止签到")
                await browser.close()
                elapsed = int(time.time() - start)
                self._print_stats(elapsed)
                self._send_wechat()
                sys.exit(0)

            if not tiebas:
                self.logger.error("🚫 无关注贴吧，终止")
                await browser.close()
                sys.exit(1)

            await self._sign_all(context, tiebas)
            await browser.close()

        elapsed = int(time.time() - start)
        self._print_stats(elapsed)
        self._write_json_stats(elapsed)
        self._send_wechat()
        sys.exit(1 if self.fail_list and not self._cookie_expired.is_set() else 0)

    def run(self):
        asyncio.run(self._run_async())


if __name__ == "__main__":
    TiebaSigner().run()
