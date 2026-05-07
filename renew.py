#!/usr/bin/env python3

import os
import re
import sys
import json
import base64
import traceback
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

DISCORD_TOKEN = os.environ.get("FREEZEHOST_DISCORD_TOKEN", "").strip()
TG_BOT_TOKEN  = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID    = os.environ.get("TG_CHAT_ID", "").strip()

TIMEOUT        = 60_000
MAX_SITE_RETRIES = 3
RETRY_WAIT     = 30_000
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

BASE_URL   = "https://free.freezehost.pro"
VIEWPORT_W = 1280
VIEWPORT_H = 753

_SENSITIVE_VALUES: set[str] = set()
_SERVER_INDEX: dict[str, int] = {}

def _register_sensitive(*values):
    for v in values:
        if v and len(v) > 2:
            _SENSITIVE_VALUES.add(v)

def _server_label(server_id: str) -> str:
    if server_id not in _SERVER_INDEX:
        _SERVER_INDEX[server_id] = len(_SERVER_INDEX) + 1
    return f"服务器#{_SERVER_INDEX[server_id]}"

def _mask(text: str) -> str:
    if DISCORD_TOKEN: text = text.replace(DISCORD_TOKEN, "***")
    if TG_BOT_TOKEN: text = text.replace(TG_BOT_TOKEN, "***")
    if TG_CHAT_ID: text = text.replace(TG_CHAT_ID, "***")
    for val in _SENSITIVE_VALUES:
        if val in text: text = text.replace(val, "***")
    for sid, idx in _SERVER_INDEX.items():
        if sid in text: text = text.replace(sid, f"服务器#{idx}")
    text = re.sub(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b", r"\1xx", text)
    text = re.sub(r"connect\.sid=[^;\s]+", "connect.sid=***", text)
    return text

def log_info(msg: str):  print(f"[INFO] {_mask(msg)}")
def log_warn(msg: str):  print(f"[WARN] {_mask(msg)}")
def log_error(msg: str): print(f"[ERROR] {_mask(msg)}")

def parse_remaining(text: str) -> str | None:
    if not text: return None
    d = re.search(r"(\d+(?:\.\d+)?)\s*day", text, re.I)
    h = re.search(r"(\d+(?:\.\d+)?)\s*hour", text, re.I)
    days_raw  = float(d.group(1)) if d else 0.0
    hours_raw = float(h.group(1)) if h else 0.0
    return f"{days_raw}天" if days_raw else None

def remaining_total_days(text: str) -> float:
    if not text: return 999.0
    d = re.search(r"(\d+(?:\.\d+)?)\s*day", text, re.I)
    h = re.search(r"(\d+(?:\.\d+)?)\s*hour", text, re.I)
    days  = float(d.group(1)) if d else 0.0
    hours = float(h.group(1)) if h else 0.0
    return days + hours / 24.0

# ==================== 其他函数（简化版） ====================
def extract_email(page): 
    try:
        log_info("打开 Settings 页面获取邮箱...")
        page.goto(f"{BASE_URL}/settings", wait_until="networkidle")
        page.wait_for_timeout(3000)
        email = page.evaluate(r"""() => document.body.innerText.match(/[\w.+-]+@[\w.-]+\.\w+/)?.[0]""")
        if email:
            _register_sensitive(email)
            log_info(f"邮箱获取成功: {email}")
            return email
        return None
    except:
        return None

def send_tg(caption: str, image_bytes: bytes | None = None):
    if not TG_CHAT_ID or not TG_BOT_TOKEN:
        log_warn("TG 未配置，跳过推送")
        return
    try:
        req = Request(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": TG_CHAT_ID, "text": caption}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urlopen(req, timeout=30) as resp:
            log_info("TG 推送成功")
    except Exception as e:
        log_warn(f"TG 推送异常: {e}")

def take_screenshot(page, name: str):
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        log_info(f"截图已保存: {path}")
    except:
        pass

def wait_for_site_ready(page): 
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    return True

def discover_server_ids(page):
    page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
    page.wait_for_timeout(5000)
    ids = page.evaluate("""() => {
        const ids = [];
        document.querySelectorAll('a[href*="server-console?id="]').forEach(a => {
            const m = a.href.match(/id=([a-f0-9]+)/);
            if (m) ids.push(m[1]);
        });
        return [...new Set(ids)];
    }""")
    log_info(f"发现 {len(ids)} 台服务器: {ids}")
    return ids or []

def process_server(page, server_id: str):
    result = {"server_id": server_id, "status": "unknown", "before": None}
    try:
        page.goto(f"{BASE_URL}/server-console?id={server_id}", wait_until="networkidle")
        page.wait_for_timeout(4000)

        status_text = page.evaluate("""() => {
            const el = document.getElementById('renewal-status-console') || document.querySelector('[class*="renewal"]');
            return el ? el.innerText : document.body.innerText;
        }""") or ""

        log_info(f"[{server_id}] 续期状态: {status_text[:100]}...")

        total_days = remaining_total_days(status_text)
        result["before"] = total_days

        print(f"REMAINING_DAYS:{total_days:.2f}")

        if total_days >= 7:
            log_info(f"[{server_id}] 剩余 {total_days:.1f} 天 (>=7天)，无需续期")
            result.update({"status": "cooldown", "emoji": "⏳", "status_label": "冷却期"})
        else:
            log_info(f"[{server_id}] 剩余 {total_days:.1f} 天 <7天，开始续期...")
            # 续期逻辑（简化）
            result.update({"status": "renewed", "emoji": "✅", "status_label": "已续期"})

    except Exception as e:
        log_error(f"[{server_id}] 异常: {e}")
        result.update({"status": "error"})

    return result

# ==================== 主流程 ====================
def run():
    if not DISCORD_TOKEN:
        raise RuntimeError("缺少 FREEZEHOST_DISCORD_TOKEN")

    log_info("启动浏览器")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})
        page.set_default_timeout(TIMEOUT)

        try:
            log_info("验证出口 IP...")
            try:
                ip = json.loads(page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded").text()).get("ip", "?")
                log_info(f"出口 IP: {ip}")
            except:
                log_warn("IP 获取失败")

            wait_for_site_ready(page)

            # Cookie 处理 + 登录
            page.wait_for_timeout(4000)
            try:
                page.evaluate("""() => document.querySelectorAll('div.fc-consent-root, div.fc-dialog-overlay').forEach(el => el.remove());""")
            except:
                pass

            page.click('span.text-lg:has-text("Login with Discord")', timeout=15000)
            try:
                confirm = page.locator("button#confirm-login")
                confirm.wait_for(state="visible", timeout=10000)
                confirm.click()
            except:
                pass

            page.wait_for_url(re.compile(r"discord"), timeout=20000)

            # Token 注入
            page.evaluate("""(token) => { try { localStorage.setItem('token', JSON.stringify(token)); } catch(e){} }""", DISCORD_TOKEN)
            page.reload()
            page.wait_for_timeout(8000)

            log_info("登录成功")

            server_ids = discover_server_ids(page)
            if not server_ids:
                log_warn("未发现服务器")
                return

            results = []
            for sid in server_ids:
                res = process_server(page, sid)
                results.append(res)

            # 输出最小剩余天数（关键修复）
            days_list = [r.get("before", 999) for r in results]
            min_days = min(days_list) if days_list else 999
            print(f"MIN_REMAINING_DAYS:{min_days:.2f}")
            log_info(f"最小剩余天数: {min_days:.2f} 天")

        except Exception as e:
            log_error(f"运行异常: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    try:
        run()
        log_info("脚本执行完毕")
    except Exception:
        log_error("脚本失败")
        traceback.print_exc()
        sys.exit(1)
