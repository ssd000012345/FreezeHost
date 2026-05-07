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
    extra_hours = (days_raw - int(days_raw)) * 24
    total_hours = hours_raw + extra_hours
    final_days  = int(days_raw)
    final_hours = int(total_hours)
    final_mins  = int(round((total_hours - final_hours) * 60))
    parts = []
    if final_days > 0: parts.append(f"{final_days}天")
    if final_hours > 0 or final_days > 0: parts.append(f"{final_hours}时")
    parts.append(f"{final_mins}分")
    return "".join(parts) if parts else None

def remaining_total_days(text: str) -> float | None:
    if not text: return None
    d = re.search(r"(\d+(?:\.\d+)?)\s*day", text, re.I)
    h = re.search(r"(\d+(?:\.\d+)?)\s*hour", text, re.I)
    days  = float(d.group(1)) if d else 0.0
    hours = float(h.group(1)) if h else 0.0
    return days + hours / 24.0

def extract_email(page) -> str | None:
    try:
        log_info("打开 Settings 页面获取邮箱...")
        page.goto(f"{BASE_URL}/settings", wait_until="networkidle")
        page.wait_for_timeout(3000)
        email = page.evaluate(r"""() => {
            const labels = document.querySelectorAll('p');
            for (const label of labels) {
                if (label.textContent.trim().toLowerCase().includes('email address')) {
                    const next = label.nextElementSibling;
                    if (next) {
                        const text = next.textContent.trim();
                        if (text.includes('@')) return text;
                    }
                }
            }
            const body = document.body.innerText;
            const m = body.match(/[\w.+-]+@[\w.-]+\.\w+/);
            return m ? m[0] : null;
        }""")
        if email:
            _register_sensitive(email)
            log_info(f"邮箱获取成功: {email}")
            return email
        return None
    except Exception as e:
        log_warn(f"获取邮箱失败: {e}")
        return None

def send_tg(caption: str, image_bytes: bytes | None = None):
    if not TG_CHAT_ID or not TG_BOT_TOKEN:
        log_warn("TG 未配置，跳过推送")
        return
    try:
        if image_bytes:
            boundary = f"----Boundary{abs(hash(caption))}"
            body_parts = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{TG_CHAT_ID}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"s.png\"\r\nContent-Type: image/png\r\n\r\n"
            ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
            req = Request(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto", data=body_parts, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
        else:
            req = Request(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", data=json.dumps({"chat_id": TG_CHAT_ID, "text": caption}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=30) as resp:
            log_info("TG 推送成功" if resp.status == 200 else f"TG 推送失败: HTTP {resp.status}")
    except Exception as e:
        log_warn(f"TG 推送异常: {e}")

def take_screenshot(page, name: str) -> bytes | None:
    try:
        page.set_viewport_size({"width": VIEWPORT_W, "height": VIEWPORT_H})
        page.wait_for_timeout(500)
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        log_info(f"截图已保存: {path}")
        return path.read_bytes()
    except Exception as e:
        log_warn(f"截图失败: {e}")
        return None

def merge_screenshots(browser, buffers: list[bytes]) -> bytes | None:
    if not buffers: return None
    pg = browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})
    try:
        imgs = "".join(f'<img src="data:image/png;base64,{base64.b64encode(b).decode()}" style="width:100%;border-radius:8px;border:2px solid #202225;box-shadow:0 4px 6px rgba(0,0,0,.3);" />' for b in buffers)
        pg.set_content(f'<body style="margin:0;padding:15px;background:#2f3136;display:flex;flex-direction:column;gap:15px;">{imgs}</body>')
        pg.wait_for_timeout(500)
        return pg.screenshot(full_page=True)
    except:
        return None
    finally:
        pg.close()

def check_site_down(page) -> bool:
    try:
        return page.evaluate("""() => {
            const body = document.body ? document.body.innerText : '';
            return body.includes('CONNECTION TO THE MANAGEMENT SERVICES LOST') || (body.includes('Retrying in') && body.includes('Retry Now'));
        }""")
    except:
        return False

def wait_for_site_ready(page) -> bool:
    for attempt in range(1, MAX_SITE_RETRIES + 1):
        log_info(f"加载 FreezeHost 首页 (尝试 {attempt}/{MAX_SITE_RETRIES})...")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT)
        except:
            if attempt < MAX_SITE_RETRIES: page.wait_for_timeout(RETRY_WAIT)
            continue
        page.wait_for_timeout(3000)
        if check_site_down(page):
            take_screenshot(page, f"site-down-{attempt}")
            if attempt < MAX_SITE_RETRIES: page.wait_for_timeout(RETRY_WAIT)
            continue
        try:
            if page.locator('span.text-lg:has-text("Login with Discord")').is_visible():
                log_info("首页加载正常，登录按钮可见")
                return True
        except:
            pass
        return True
    return False

def discover_server_ids(page) -> list[str]:
    for attempt in range(3):
        captured = set()
        def on_req(req):
            m = re.search(r"/api/server.*?id=([a-f0-9]+)", req.url, re.I)
            if m: captured.add(m.group(1))
        page.on("request", on_req)
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(5000)
        page.remove_listener("request", on_req)

        js_ids = page.evaluate(r"""() => {
            const ids = [];
            if (typeof serverData !== 'undefined' && Array.isArray(serverData))
                serverData.forEach(s => { if (s.identifier) ids.push(s.identifier); });
            return ids;
        }""")
        all_ids = set(js_ids or []) | captured
        if all_ids:
            log_info(f"发现 {len(all_ids)} 台服务器")
            return sorted(all_ids)
        if attempt < 2: page.wait_for_timeout(3000)
    return []

def process_server(page, server_id: str) -> dict:
    result = dict(server_id=server_id, status="unknown", before=None, after=None, emoji="❓", status_label="未知", detail="")
    try:
        page.goto(f"{BASE_URL}/server-console?id={server_id}", wait_until="networkidle")
        page.wait_for_timeout(3000)

        status_text = page.evaluate("""() => {
            const el = document.getElementById('renewal-status-console');
            return el ? el.innerText.trim() : null;
        }""")
        log_info(f"[{server_id}] 续期状态: {status_text or '(空)'}")

        remaining_before = parse_remaining(status_text)
        total_days = remaining_total_days(status_text)
        result["before"] = remaining_before

        # ==================== 修改重点：小于7天才续期 ====================
        if total_days is not None and total_days >= 7:
            log_info(f"[{server_id}] 剩余 {total_days:.1f} 天 (>=7天)，无需续期")
            print(f"REMAINING_DAYS:{total_days:.2f}")   # 供 Workflow 提取
            result.update(status="cooldown", emoji="⏳", status_label="冷却期", detail=remaining_before or f"{total_days:.1f}天")
            return result

        log_info(f"[{server_id}] 剩余 {total_days:.1f} 天 < 7天，开始续期...")
        print(f"REMAINING_DAYS:{total_days:.2f}")

        # 续期逻辑（简化版）
        renew_href = page.evaluate("""() => {
            const rl = document.getElementById('renew-link-modal');
            if (rl) { const h = rl.getAttribute('href'); if (h && h !== '#') return {href:h}; }
            for (const a of document.querySelectorAll('a[href*="renew"]')) {
                const h = a.getAttribute('href');
                if (h && h.includes('renew')) return {href:h};
            }
            return null;
        }""")

        if renew_href and renew_href.get("href"):
            page.goto(urljoin(page.url, renew_href["href"]), wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if "success=RENEWED" in page.url:
                log_info(f"[{server_id}] 续期成功！")
                result.update(status="renewed", emoji="✅", status_label="续期成功")
            else:
                result.update(status="unknown", emoji="❓", status_label="续期结果未知")
        else:
            result.update(status="no_renew_link", emoji="⚠️", status_label="未找到续期按钮")

    except Exception as e:
        log_error(f"[{server_id}] 异常: {e}")
        result.update(status="error", emoji="❌", status_label="脚本异常")

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

        display_name = "未知用户"
        try:
            log_info("验证出口 IP...")
            try:
                ip = json.loads(page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded").text()).get("ip", "?")
                log_info(f"出口 IP: {ip}")
            except:
                log_warn("IP 验证失败")

            if not wait_for_site_ready(page):
                log_warn("站点不可用")
                return

            # Cookie 处理
            page.wait_for_timeout(4000)
            try:
                page.evaluate("""() => { document.querySelectorAll('div.fc-consent-root, div.fc-dialog-overlay').forEach(el => el.remove()); }""")
            except:
                pass

            page.click('span.text-lg:has-text("Login with Discord")', timeout=15000)

            confirm_btn = page.locator("button#confirm-login")
            confirm_btn.wait_for(state="visible")
            confirm_btn.click()

            page.wait_for_url(re.compile(r"discord\.com"), timeout=20000)

            # Token 注入
            page.evaluate("""(token) => {
                const f = document.createElement('iframe'); f.style.display = 'none';
                document.body.appendChild(f);
                f.contentWindow.localStorage.setItem('token', '"'+token+'"');
                try { localStorage.setItem('token', '"'+token+'"'); } catch(e){}
                document.body.removeChild(f);
            }""", DISCORD_TOKEN)

            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            page.wait_for_url(lambda u: "/dashboard" in u, timeout=30000)
            log_info("登录成功")

            email = extract_email(page)
            if email: display_name = email

            server_ids = discover_server_ids(page)
            if not server_ids:
                buf = take_screenshot(page, "no-servers")
                send_tg(f"用户：{display_name}\n⚠️ 未发现服务器", buf)
                return

            results = []
            for sid in server_ids:
                res = process_server(page, sid)
                results.append(res)

            # 输出最小剩余天数供 Workflow 使用
            days_list = [remaining_total_days(r.get("before", "")) or 999 for r in results]
            min_days = min(days_list) if days_list else 999
            print(f"MIN_REMAINING_DAYS:{min_days:.2f}")
            log_info(f"最小剩余天数: {min_days:.2f} 天")

            # TG 推送
            lines = [f"服务器: {r['server_id']} | {r['emoji']}{r['status_label']} {r.get('detail','')}" for r in results]
            send_tg("\n".join([f"用户：{display_name}", *lines, "", "FreezeHost Auto Renew"]))

        except Exception as e:
            log_error(f"运行异常: {e}")
            traceback.print_exc()
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
