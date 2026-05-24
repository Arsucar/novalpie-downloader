# coding=utf-8
"""
登录获取 Cookie 测试脚本

用 Playwright 打开浏览器，用户手动登录后自动检测登录状态并提取 Cookie。
用法: python -m novalpie.login_cookie
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[x] 请先安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

from . import config


def _check_login_status(page) -> str:
    """检测页面登录状态，返回 'logged_in' / 'not_logged_in' / 'unknown'"""
    try:
        # 检查常见的已登录指示器
        logged_in_indicators = [
            # 用户头像/菜单
            "img[class*='avatar']",
            "img[class*='user']",
            ".user-avatar",
            ".user-info",
            "[class*='avatar']",
            # 用户名/登出按钮
            "a[href*='logout']",
            "a[href*='signout']",
            "button[class*='logout']",
            "[class*='user-name']",
            "[class*='username']",
            "[class*='nickname']",
            # 会员/VIP 标识
            "[class*='vip']",
            "[class*='member']",
        ]
        for sel in logged_in_indicators:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return "logged_in"

        # 检查是否存在登录/注册按钮（未登录指示器）
        not_logged_in_indicators = [
            "a[href*='login']",
            "a[href*='signin']",
            "button[class*='login']",
            "[class*='login-btn']",
            "[class*='sign-in']",
            "text=登录",
            "text=登 录",
            "text=Sign In",
        ]
        for sel in not_logged_in_indicators:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return "not_logged_in"
            except Exception:
                continue

        return "unknown"
    except Exception:
        return "unknown"


def login_and_save_cookie(
    site_url: str = "",
    cookie_path: str = "",
    headless: bool = False,
    max_wait_sec: int = 300,
) -> str | None:
    """
    打开浏览器让用户登录，自动检测登录成功后提取 Cookie 并保存。

    返回: Cookie 字符串，失败返回 None
    """
    site_url = site_url or config.base_url
    cookie_path = cookie_path or config.cookieFilePath

    parsed = urlparse(site_url)
    domain = parsed.hostname or ""
    if not domain:
        print(f"[x] 无效的站点地址: {site_url}")
        return None

    print(f"[*] 将打开浏览器访问: {site_url}")
    print("[*] 请在浏览器中手动登录")
    print(f"[*] 最长等待 {max_wait_sec} 秒，登录成功后将自动检测并提取 Cookie")
    print("[*] 也可以随时在此终端按 Enter 提前提取 Cookie，输入 q 取消")
    print()

    cookie_line = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=config.DEFAULT_HEADERS["User-Agent"],
            locale="zh-CN",
        )
        page = context.new_page()

        page.goto(site_url, wait_until="domcontentloaded", timeout=config.pageGotoTimeoutMs)
        print("[*] 浏览器已打开，等待登录...")

        # 轮询检测登录状态
        start = time.monotonic()
        poll_interval = 3.0  # 每3秒检测一次
        last_status = "unknown"
        detected = False

        while time.monotonic() - start < max_wait_sec:
            # 非阻塞检测：先检查是否有终端输入
            status = _check_login_status(page)

            if status != last_status:
                last_status = status
                if status == "logged_in":
                    print("[+] 检测到已登录！正在提取 Cookie...")
                    detected = True
                    break
                elif status == "not_logged_in":
                    print("[*] 当前未登录，请在浏览器中登录...")

            # 等待一段时间再检测
            page.wait_for_timeout(int(poll_interval * 1000))

        if not detected:
            # 超时，尝试最后一次提取
            print("[!] 等待超时，尝试提取当前 Cookie...")

        # 提取 Cookie
        cookies = context.cookies()

        # 先打印所有 Cookie 供调试
        print(f"\n[*] 浏览器中共有 {len(cookies)} 个 Cookie:")
        for i, c in enumerate(cookies):
            c_domain = c.get("domain", "")
            c_name = c.get("name", "")
            c_value = c.get("value", "")
            c_path = c.get("path", "")
            c_httponly = c.get("httpOnly", False)
            c_secure = c.get("secure", False)
            print(f"  [{i+1}] domain={c_domain}  name={c_name}  value={c_value[:20]}...  path={c_path}  httpOnly={c_httponly}  secure={c_secure}")

        # 匹配站点 Cookie
        site_cookies = [
            c for c in cookies
            if domain in c.get("domain", "").lstrip(".")
               or c.get("domain", "").lstrip(".").endswith(domain)
        ]

        if not site_cookies:
            parts = domain.split(".")
            if len(parts) >= 2:
                top_domain = ".".join(parts[-2:])
                site_cookies = [
                    c for c in cookies
                    if top_domain in c.get("domain", "").lstrip(".")
                ]

        # 提取 localStorage 和 sessionStorage
        print("\n[*] 正在提取 localStorage 数据...")
        local_storage = page.evaluate("() => { const d = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); d[k] = localStorage.getItem(k); } return d; }")
        if local_storage:
            print(f"[*] localStorage 共 {len(local_storage)} 项:")
            for k, v in local_storage.items():
                v_preview = str(v)[:50]
                print(f"    {k} = {v_preview}...")
        else:
            print("[*] localStorage 为空")

        print("\n[*] 正在提取 sessionStorage 数据...")
        session_storage = page.evaluate("() => { const d = {}; for (let i = 0; i < sessionStorage.length; i++) { const k = sessionStorage.key(i); d[k] = sessionStorage.getItem(k); } return d; }")
        if session_storage:
            print(f"[*] sessionStorage 共 {len(session_storage)} 项:")
            for k, v in session_storage.items():
                v_preview = str(v)[:50]
                print(f"    {k} = {v_preview}...")
        else:
            print("[*] sessionStorage 为空")

        # 构建认证信息
        # 优先使用 localStorage/sessionStorage 中的 token
        auth_token = None
        auth_source = ""

        # 常见的 token 键名
        token_keys = [
            "token", "auth_token", "access_token", "jwt", "jwt_token",
            "user_token", "login_token", "session_token", "bearer_token",
            "Authorization", "authorization",
        ]

        for storage_name, storage_data in [("localStorage", local_storage), ("sessionStorage", session_storage)]:
            if not storage_data:
                continue
            for key in token_keys:
                for actual_key, value in storage_data.items():
                    if key.lower() in actual_key.lower() and value:
                        auth_token = value
                        auth_source = f"{storage_name}.{actual_key}"
                        break
                if auth_token:
                    break
            if auth_token:
                break

        # 格式化 Cookie 字符串
        cookie_parts = []
        for c in site_cookies:
            name = c.get("name", "")
            value = c.get("value", "")
            if name and value:
                cookie_parts.append(f"{name}={value}")

        cookie_line = "; ".join(cookie_parts) if cookie_parts else ""

        # 如果找到了 auth token，保存到单独的 .token 文件
        if auth_token:
            print(f"\n[+] 发现认证 Token: {auth_source}")
            print(f"    值: {auth_token[:40]}...")

        if not site_cookies and not auth_token:
            # 兜底：把所有 localStorage 数据都保存
            all_storage = {**local_storage, **session_storage}
            if all_storage:
                print(f"\n[!] 未找到 Cookie 或 Token，将保存全部 storage 数据")
                storage_parts = [f"{k}={v}" for k, v in all_storage.items() if v]
                cookie_line = "; ".join(storage_parts)
            else:
                print("[!] 未检测到任何认证信息，请确认已登录")
                context.close()
                browser.close()
                return None

        # 保存 JWT token 到 .token 文件
        if auth_token:
            try:
                token_path = Path(cookie_path).with_suffix(".token")
                token_path.write_text(auth_token + "\n", encoding="utf-8")
                print(f"[+] JWT Token 已保存到: {token_path.resolve()}")
            except Exception as e:
                print(f"[!] 保存 Token 文件失败: {e}")

        # 保存 Cookie 到 .txt 文件（仅当有站点 Cookie 时）
        if cookie_line:
            try:
                save_path = Path(cookie_path)
                save_path.write_text(cookie_line + "\n", encoding="utf-8")
                print(f"[+] Cookie 已保存到: {save_path.resolve()}")
            except Exception as e:
                print(f"[!] 保存 Cookie 文件失败: {e}")
                print("[*] Cookie 字符串如下，请手动保存:")
                print(cookie_line)
        else:
            print("[*] 无站点 Cookie，跳过 Cookie 文件保存")

        context.close()
        browser.close()

    return cookie_line


def main():
    cookie = login_and_save_cookie()
    if cookie:
        print("\n[*] Cookie 获取成功！现在可以用这个 Cookie 下载小说了。")
    else:
        print("\n[x] Cookie 获取失败或已取消。")
        sys.exit(1)


if __name__ == "__main__":
    main()
