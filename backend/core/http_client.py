"""精简版 HTTP 客户端 — Fetcher + StealthySession 双级降级.

国内源（好游快爆/TapTap）通常不需要复杂反爬，但保留降级能力。
"""

from __future__ import annotations

import asyncio
import random
import threading
from urllib.parse import urlparse

from backend.config import get_settings
from backend.logging_setup import get_logger

logger = get_logger()

# 全局 TLS 指纹轮换池
_FINGERPRINT_POOL = [
    "chrome_124", "chrome_120", "chrome_122", "chrome_123", "chrome_121",
]
_fp_lock = threading.Lock()
_fp_index = 0


def _next_fingerprint() -> str:
    global _fp_index
    with _fp_lock:
        fp = _FINGERPRINT_POOL[_fp_index % len(_FINGERPRINT_POOL)]
        _fp_index += 1
        return fp


async def http_get(url: str, timeout: float | None = None) -> tuple[int, str]:
    """发送 GET 请求 — aiohttp 优先 (国内站无需 TLS 指纹), Scrapling 可选备用.

    PyInstaller 环境 Scrapling 缺 fingerprint 数据文件会崩, 所以 aiohttp 放第一位.
    """
    settings = get_settings()
    effective_timeout = timeout or settings.request_timeout

    # SSRF 防护: 验证 URL
    url = validate_url(url)

    # ── 方案 1: aiohttp (优先, 稳定, 无依赖问题) ──
    status, html = await _aiohttp_get(url, effective_timeout)
    if status == 200 and len(html) > 200:
        return status, html

    # ── 方案 2: Scrapling Fetcher (仅当 aiohttp 失败时尝试) ──
    try:
        from scrapling import Fetcher
        proxy = settings.domestic_proxy or settings.proxy or None
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        fetcher = Fetcher(auto_referer=True, catch_errors=True,
                          browser_fp={"browser": _next_fingerprint()})
        resp = await asyncio.to_thread(
            fetcher.get, url, headers=headers,
            proxy=proxy, timeout=int(effective_timeout),
        )
        if resp:
            # Scrapling v0.3+: resp.status (int), resp.body (bytes)
            status_code = resp.status if hasattr(resp, "status") else (
                resp.status_code if hasattr(resp, "status_code") else 0)
            body = resp.body if hasattr(resp, "body") else (
                resp.content if hasattr(resp, "content") else b"")
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            if status_code == 200 and len(body) > 200:
                return 200, str(body)
    except Exception as e:
        logger.debug("Scrapling fallback failed for {}: {}", url[:60], e)

    return status, html  # 返回 aiohttp 的结果


async def _aiohttp_get(url: str, timeout: float) -> tuple[int, str]:
    """aiohttp 降级方案."""
    try:
        import aiohttp
        settings = get_settings()
        proxy = settings.domestic_proxy or settings.proxy or None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    return 200, html
                return resp.status, ""
    except Exception as e:
        return 0, str(e)


async def stealth_get(url: str, timeout: float | None = None) -> tuple[int, str]:
    """使用 StealthySession (Chromium 无头) 渲染页面.

    用于 TapTap 等动态加载页面。调用前需确保 BrowserManager 已启动。
    """
    settings = get_settings()
    effective_timeout = timeout or settings.stealth_timeout

    # SSRF 防护: 验证 URL
    url = validate_url(url)

    try:
        from backend.core.browser_manager import get_browser_manager
        mgr = get_browser_manager()
        if not mgr.available:
            return 0, "Browser not available"

        page, sem = await mgr.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=effective_timeout * 1000)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            html = await page.content()
            return 200, html
        finally:
            await mgr.close_page(page, sem)
    except Exception as e:
        logger.debug("stealth_get error: {}", e)
        return 0, str(e)


def is_cloudflare_block(html: str) -> bool:
    """检测页面是否为 Cloudflare 拦截页面."""
    if not html:
        return False
    cf_markers = [
        "cf-browser-verification", "cf-challenge-running",
        "Just a moment...", "Checking your browser",
        "cf-turnstile", "challenge-platform",
        "_cf_chl_opt", "cf_chl_",
    ]
    html_lower = html.lower()
    return any(m.lower() in html_lower for m in cf_markers)


def validate_url(url: str, allow_all_https: bool = True) -> str:
    """验证 URL 安全性 (SSRF 防护, DNS 解析 + 私有 IP 拦截).

    Args:
        url: 待验证 URL
        allow_all_https: 始终为 True (国内系统无域名白名单, 仅拦截私有 IP)

    Returns:
        规范化后的 URL

    Raises:
        ValueError: URL 无效或不安全
    """
    import socket as _socket

    if not url or not isinstance(url, str):
        raise ValueError("URL 为空")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的协议: {parsed.scheme}")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("无法提取主机名")

    # 1. 字符串级私有/回环 IP 快速拦截
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        raise ValueError("禁止访问内网地址")

    _private_prefixes = [
        (10, 0, 0), (127, 0, 0), (169, 254, 0),
        (172, 16, 31), (192, 168, 0),
    ]
    parts = hostname.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        for pre_a, lo_b, hi_b in _private_prefixes:
            if a == pre_a:
                if hi_b == 0 or (lo_b <= b <= hi_b):
                    raise ValueError("禁止访问内网地址")

    # 2. DNS 解析后私有 IP 拦截 (防 DNS rebinding)
    try:
        resolved = _socket.getaddrinfo(hostname, None, _socket.AF_INET)
        seen = set()
        for _family, _type, _proto, _cname, sockaddr in resolved:
            ip = sockaddr[0]
            if ip in seen:
                continue
            seen.add(ip)
            parts_ip = ip.split(".")
            if len(parts_ip) == 4 and all(p.isdigit() for p in parts_ip):
                a, b = int(parts_ip[0]), int(parts_ip[1])
                for pre_a, lo_b, hi_b in _private_prefixes:
                    if a == pre_a and (hi_b == 0 or lo_b <= b <= hi_b):
                        raise ValueError(f"域名 {hostname} 解析到内网 IP: {ip}")
    except _socket.gaierror:
        raise ValueError(f"域名解析失败: {hostname}")

    return url
