"""国内新游定时抓取服务 — 好游快爆 + TapTap + 熔断保护.

修正 PROMOTE.md 中的所有 API 错误:
- http_get 返回 (status, html) 而非单独 html
- browser_manager 使用 new_page() + close_page() 而非 get_page()
- ElementHandle 不支持 inner_text(selector), 需先 query_selector
- 每个 select_one 后判 None 防止 AttributeError
- 完整的熔断器集成 + 重试 + 超时控制
"""

from __future__ import annotations

import asyncio
import json as _json_lib
import random
import re
import threading
import uuid as _uuid
from datetime import datetime, timezone, timedelta, date
from urllib.parse import urlparse, parse_qs, quote

from bs4 import BeautifulSoup

from backend.config import get_settings
from backend.core.http_client import http_get, stealth_get, is_cloudflare_block
from backend.db.database import get_connection
from backend.logging_setup import get_logger

logger = get_logger()

_last_modified: datetime | None = None
_last_modified_lock = threading.Lock()

# ── 爬虫事件日志 (内存缓冲, 前端轮询展示) ─────────────────
_MAX_LOG_ENTRIES = 50
_crawl_log: list[dict] = []
_crawl_log_lock = threading.Lock()


def add_log(source: str, event: str, message: str = "") -> None:
    """向事件日志追加一条记录."""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "event": event,        # "start" | "done" | "error" | "circuit_open"
        "message": message,
    }
    with _crawl_log_lock:
        _crawl_log.append(entry)
        if len(_crawl_log) > _MAX_LOG_ENTRIES:
            _crawl_log[:] = _crawl_log[-_MAX_LOG_ENTRIES:]


def get_crawl_log(limit: int = 20) -> list[dict]:
    """获取最近的爬虫事件日志."""
    with _crawl_log_lock:
        return list(_crawl_log[-limit:])

# 好游快爆页面选择器（外部化，方便改版时修改）
# 实际 DOM 结构 (已验证 2025-06):
#   .foreCard > .foreCard-hd (date) + .foreCard-bd > .foreList > li (each game)
#   li > a > .img img + .con > .name em (name) + .tags .it (tags) + .info .score
_3839_SELECTORS = {
    "date_block": [".foreCard"],                          # 每个日期分组
    "date": [".foreCard-hd"],                             # 日期文本 (如 "06月08日 星期一")
    "item": [".foreList li"],                             # 单个游戏条目
    "name": [".name em", ".con .name em"],                # 游戏名
    "icon": [".img img", "img[src]"],                     # 游戏图标
    "tags": [".tags .it"],                                # 标签 (多平台、角色扮演等)
    "score": [".score"],                                  # 评分
    "desc": [".info span:last-child"],                    # 描述文字
    "link": [".con"],                                     # 通过父级 a 标签取 href
    "btn_reserve": [".btn.btnY"],                         # 预约按钮
    "btn_download": [".btn.btnG"],                        # 下载按钮
}

# TapTap 页面选择器（SPA 需 Playwright 渲染后使用）
# 渲染后可用的实际 class: daily-event-app-info, calendar-slide-item, app-calendar
_TAPTAP_SELECTORS = {
    "container": [
        ".daily-event-app-info",
        ".calendar-slide-item",
        ".daily-event-small-row-card",
        "[class*='daily-event']",
    ],
    "name": [
        ".daily-event-app-info__title",
        ".calendar-slide-item__text",
        "[class*='__title']",
    ],
    "date": [
        ".daily-event-big-card__time",
        ".calendar-slide-item-date__text",
        "[class*='__time']",
        "[class*='date__text']",
    ],
    "tag": [
        ".daily-event-app-info__tag",
        ".label-list-tag",
        "[class*='__tag']",
    ],
    "icon": [
        ".daily-event-app-info__app-icon img",
        ".app-icon__img",
        "img[src]",
    ],
    "link": ["a[href]"],
}

# Android 包名格式校验
_PKG_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_.]{1,127}$')

# 中文日期解析
_CN_DATE_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
_CN_DATE2_RE = re.compile(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})')
_CN_DATE3_RE = re.compile(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日')  # 无年份，补当前年

# 注: 已移除游戏类别过滤和名称后缀清理 (v1.2)
# 所有类型游戏均需爬取，原始名称完整保留


def set_last_modified(dt: datetime) -> None:
    with _last_modified_lock:
        global _last_modified
        _last_modified = dt


def get_last_modified() -> datetime | None:
    with _last_modified_lock:
        return _last_modified


# ── 工具函数 ───────────────────────────────────────────────

def slugify(text: str) -> str:
    """将中文游戏名转为拼音首字母 + 英文单词的 slug.

    策略: 中文部分取拼音首字母缩写, 英文部分保留原词。
    如 "王者荣耀" → "wzry", "原神 Genshin Impact" → "ys_genshin_impact"
    """
    if not text:
        return "unknown"

    # 简单策略：保留 ASCII 字符，中文用其 Unicode 码点简写
    parts = []
    ascii_buffer = []
    chinese_count = 0
    chinese_codes = []

    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            if ascii_buffer:
                parts.append(''.join(ascii_buffer).strip().lower())
                ascii_buffer = []
            chinese_count += 1
            chinese_codes.append(str(ord(ch) % 1000))
        elif ch.isalnum() or ch in '_-':
            ascii_buffer.append(ch)
        elif ch.isspace():
            if ascii_buffer:
                ascii_buffer.append('_')
            elif parts and not parts[-1].endswith('_'):
                ascii_buffer.append('_')

    if ascii_buffer:
        parts.append(''.join(ascii_buffer).strip().lower())

    # 去空去重
    parts = [p.strip('_') for p in parts if p.strip('_')]

    if not parts and chinese_codes:
        parts.append('cn' + '_'.join(chinese_codes[:6]))

    result = '_'.join(parts).strip('_')
    # 清理多余下划线和非字母数字字符
    result = re.sub(r'[^a-z0-9_]', '', result)
    result = re.sub(r'_+', '_', result).strip('_')

    return result[:80] or "unknown"


def _parse_chinese_date(text: str) -> str | None:
    """解析中文日期格式.

    支持: 2026年06月08日, 2026-06-08, 06月08日
    """
    if not text:
        return None
    text = text.strip()

    # 1. 完整中文: 2026年06月08日
    m = _CN_DATE_RE.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 2. ISO: 2026-06-08 或 2026/06/08
    m = _CN_DATE2_RE.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. 无年份: 06月08日 — 补当前年份
    m = _CN_DATE3_RE.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            y = datetime.now().year
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 4. 纯数字: 20260608
    m = re.search(r'(\d{4})(\d{2})(\d{2})', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def _extract_icon(soup, selectors: list[str]) -> str:
    """从元素中提取图标 URL."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            src = el.get("data-original") or el.get("data-src") or el.get("src", "")
            if src and len(src) > 20 and "base64" not in src:
                return src
    return ""


def _safe_text(el, default: str = "") -> str:
    """安全提取元素文本."""
    if el:
        try:
            return el.get_text(strip=True)
        except Exception:
            pass
    return default


def _safe_attr(el, attr: str, default: str = "") -> str:
    """安全提取元素属性."""
    if el and hasattr(el, "get"):
        return str(el.get(attr, "") or "")
    return default


# ── 好游快爆爬虫 ──────────────────────────────────────────

async def fetch_3839_updates(full_refresh: bool = False) -> list[dict]:
    """抓取好游快爆新游预约时间轴: https://www.3839.com/timeline.html

    实际 DOM 结构 (已验证):
      .foreCard (日期块) → .foreCard-hd (日期)
      → .foreList li (游戏条目) → .img img + .con > .name em (名字) + .tags .it (标签)

    Args:
        full_refresh: True=全量, False=增量（遇已知包名提前终止）
    """
    settings = get_settings()
    if not settings.enable_3839:
        logger.info("好游快爆已禁用，跳过")
        return []

    items: list[dict] = []
    date_seen: dict[str, set[str]] = {}  # parsed_date → set[pkg] 同一日期多版块去重
    global_seen: set[str] = set()        # 全局去重（增量模式用）
    existing = _load_existing_packages("3839") if not full_refresh else set()
    url = "https://www.3839.com/timeline.html"

    # 重试
    for attempt in range(settings.retry_times + 1):
        if attempt > 0:
            await asyncio.sleep(settings.retry_delay * attempt)

        try:
            status, html = await http_get(url, timeout=settings.request_timeout)
        except Exception as e:
            logger.warning("好游快爆 http_get 异常 (attempt {}): {}", attempt + 1, e)
            continue

        if status != 200 or len(html) < 500:
            logger.warning("好游快爆页面获取失败 (attempt {}): HTTP {} len={}", attempt + 1, status, len(html))
            continue

        if is_cloudflare_block(html):
            logger.warning("好游快爆触发 Cloudflare 拦截")
            _save_debug_html("3839", html)
            await record_cf_failure("3839")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # 查找所有日期块
        date_blocks = soup.select(_3839_SELECTORS["date_block"][0])
        if not date_blocks:
            logger.warning("好游快爆 未找到 .foreCard 日期块，页面结构可能已变更")
            _save_debug_html("3839", html)
            break

        logger.info("好游快爆 找到 {} 个日期块", len(date_blocks))

        for block in date_blocks:
            # ── 提取日期 ──
            date_el = block.select_one(_3839_SELECTORS["date"][0])
            block_date = _safe_text(date_el)
            block_parsed_date = _parse_chinese_date(block_date)

            # 跳过无法解析日期的块（如"待定日期"）
            if not block_parsed_date:
                continue

            # 同一日期可能有多个版块，共享去重集
            block_seen = date_seen.setdefault(block_parsed_date, set())

            # ── 遍历该日期下的游戏条目 ──
            for item_sel in _3839_SELECTORS["item"]:
                game_items = block.select(item_sel)
                if game_items:
                    break

            if not game_items:
                continue

            for li in game_items:
                # ── 游戏名 (在 .name em 或 .con .name em 中) ──
                name_el = None
                for sel in _3839_SELECTORS["name"]:
                    name_el = li.select_one(sel)
                    if name_el:
                        break
                app_name = _safe_text(name_el)
                if not app_name or len(app_name) < 2:
                    continue

                # ── 详情链接 ──
                # 第一个 a 标签是详情链接
                detail_a = li.select_one("a[href]")
                href = _safe_attr(detail_a, "href") if detail_a else ""
                if href and href.startswith("//"):
                    href = f"https:{href}"
                elif href and not href.startswith("http"):
                    href = f"https://www.3839.com{href}" if href.startswith("/") else f"https://www.3839.com/{href}"

                # ── 图标 ──
                icon_url = ""
                for sel in _3839_SELECTORS["icon"]:
                    img_el = li.select_one(sel)
                    if img_el:
                        src = img_el.get("data-original") or img_el.get("data-src") or img_el.get("lz_src") or img_el.get("src") or ""
                        if src and len(src) > 10:
                            if src.startswith("//"):
                                src = f"https:{src}"
                            icon_url = src
                            break

                # ── 标签 ──
                tags = []
                for sel in _3839_SELECTORS["tags"]:
                    tag_els = li.select(sel)
                    if tag_els:
                        tags = [_safe_text(t) for t in tag_els if _safe_text(t)]
                        break

                # ── 评分 ──
                score_el = li.select_one(_3839_SELECTORS["score"][0])
                score = _safe_text(score_el)

                # ── 活动描述 (.info span:last-child) ──
                activity_desc = ""
                info_el = li.select_one(".info")
                if info_el:
                    spans = info_el.select("span")
                    if spans:
                        # 取最后一个非空 span（排除评分 span）
                        for s in reversed(spans):
                            txt = _safe_text(s)
                            # 跳过纯评分数字（可能带小数）
                            if txt and not re.match(r'^[\d.]+$', txt):
                                activity_desc = txt
                                break

                # ── 状态徽章 (.name .g-type) ──
                status_badge = ""
                badge_el = li.select_one(".g-type")
                if badge_el:
                    status_badge = _safe_text(badge_el)

                # ── 游戏状态 (预约/下载/试玩) ──
                game_status = ""
                if li.select_one(_3839_SELECTORS["btn_reserve"][0]):
                    game_status = "预约"
                elif li.select_one(_3839_SELECTORS["btn_download"][0]):
                    btn_el = li.select_one(_3839_SELECTORS["btn_download"][0])
                    game_status = _safe_text(btn_el) or "下载"

                # 生成唯一标识 — 用详情页 URL ID 避免 slug 碰撞
                # URL 格式: //www.3839.com/a/149245.htm → 提取 149245
                url_id = ""
                if href:
                    m = re.search(r'/a/(\d+)\.htm', href)
                    if m:
                        url_id = m.group(1)
                pkg = f"3839_{url_id}" if url_id else f"3839_{slugify(app_name)}"

                # 块内去重（同一日期块不重复添加）
                if pkg in block_seen:
                    continue
                block_seen.add(pkg)

                # 增量模式：跳过已入库的游戏
                if pkg in existing:
                    global_seen.add(pkg)
                    continue

                # ── 日期：块日期（已在块级别过滤掉无法解析的） ──
                updated_at = block_parsed_date  # type: str

                items.append({
                    "icon_url": icon_url,
                    "app_name": app_name,
                    "package_name": pkg,
                    "detail_url": href,
                    "download_count": ", ".join(tags) if tags else "",
                    "version_name": score or "",
                    "version_code": "",
                    "updated_at": updated_at,
                    "activity_desc": activity_desc,
                    "status_badge": status_badge,
                    "game_status": game_status,
                })

        break  # 成功则退出重试

    if not items and attempt >= settings.retry_times:
        logger.warning("好游快爆 多次重试后仍无数据")

    return items


# ── TapTap 爬虫 ───────────────────────────────────────────

def _map_taptap_event_status(event_type: int, sub_event_type: int, title: str) -> str:
    """将 TapTap API 事件类型映射为游戏状态标签.

    event_type: 1=上线, 2=测试/试玩, 3=预约 (可能为 None)
    sub_event_type_title: 中文描述 (如 "新游预约", "新游上线", "新版本上线")
    """
    # 防御: API 可能返回 None
    et = event_type or 0
    title_lower = title.lower() if title else ""
    # 上线/发布
    if et == 1 or any(kw in title_lower for kw in ("上线", "发布", "公测", "首发", "开服")):
        return "下载"
    # 测试/试玩
    if et == 2 or any(kw in title_lower for kw in ("测试", "试玩", "内测")):
        return "试玩"
    # 预约
    if et == 3 or any(kw in title_lower for kw in ("预约", "预定")):
        return "预约"
    return ""

async def fetch_taptap_updates(full_refresh: bool = False) -> list[dict]:
    """抓取 TapTap 新游日历 — 通过 Web API 获取全量游戏数据.

    核心策略:
    1. 逐日调用 webapiv2/calendar/v1/event-list API (含 X-UA 鉴权)
    2. 全量模式扫描 90 天, 增量模式扫描 14 天
    3. 从 list_a/list_b 等所有 list_* 键提取事件
    4. 若 API 全部失败, 降级到 HTML JSON-LD 解析

    Args:
        full_refresh: True=全量扫描, False=增量扫描
    """
    settings = get_settings()
    if not settings.enable_taptap:
        logger.info("TapTap 已禁用，跳过")
        return []

    existing = _load_existing_packages("taptap") if not full_refresh else set()
    items: list[dict] = []
    seen_pkgs: set[str] = set()

    # ── X-UA 头 (模拟前端浏览器) ──
    uid_short = _uuid.uuid4().hex[:12]
    xua_raw = (
        f"V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC"
        f"&DS=Android&UID={uid_short}&OS=Windows&OSV=10&DT=PC"
    )
    xua_encoded = quote(xua_raw, safe="")

    # ── 日期范围 ──
    today = date.today()
    scan_days = 90 if full_refresh else 14
    api_base = "http://www.taptap.cn/webapiv2/calendar/v1/event-list"
    api_success_count = 0

    for day_offset in range(scan_days):
        target_date = today + timedelta(days=day_offset)
        date_ts = int(datetime(target_date.year, target_date.month, target_date.day).timestamp())
        api_url = f"{api_base}?X-UA={xua_encoded}&day={date_ts}"

        # 批次暂停 (每 20 天休息 3s 防限流)
        if day_offset > 0 and day_offset % 20 == 0:
            logger.debug("TapTap API 批次暂停 (已扫描 {} 天)", day_offset)
            await asyncio.sleep(3.0)

        try:
            status, body = await http_get(api_url, timeout=settings.request_timeout)
        except Exception as e:
            logger.debug("TapTap API 请求异常 day={}: {}", target_date, e)
            continue

        if status != 200 or len(body) < 50:
            continue

        try:
            data = _json_lib.loads(body)
        except (_json_lib.JSONDecodeError, TypeError):
            logger.debug("TapTap API JSON 解析失败 day={}", target_date)
            continue

        api_success_count += 1
        data_section = data.get("data", {}) if isinstance(data, dict) else {}

        # 遍历所有 list_* 键 (list_a, list_b, ...)
        for key, event_list in data_section.items():
            if not key.startswith("list_") or not isinstance(event_list, list):
                continue
            if not event_list:
                continue

            for event in event_list:
                if not isinstance(event, dict):
                    continue

                info = event.get("app_card_info") or {}
                game_id = str(info.get("id") or event.get("game_id") or "")
                if not game_id:
                    continue

                app_name = (info.get("title") or "").strip()
                if not app_name or len(app_name) < 2:
                    continue

                pkg = f"taptap_{game_id}"
                if pkg in seen_pkgs:
                    continue
                seen_pkgs.add(pkg)

                if pkg in existing:
                    continue

                # ── 图标 ──
                icon = info.get("icon") or {}
                icon_url = icon.get("original_url") or icon.get("large_url") or icon.get("medium_url") or ""

                # ── 评分 ──
                stat = info.get("stat") or {}
                rating = stat.get("rating") or {}
                score = str(rating.get("score") or "")

                # ── 事件类型 ──
                event_type = event.get("event_type", 0)
                sub_event_type = event.get("sub_event_type", 0)
                sub_event_title = event.get("sub_event_type_title") or ""
                game_status = _map_taptap_event_status(event_type, sub_event_type, sub_event_title)

                # ── 标签/描述: 类型标签 + 事件标题 + 预约数 ──
                tags_parts = []
                # 1. 游戏类型标签 (角色扮演, 卡牌, ...)
                genre_tags = info.get("tags") or []
                for t in genre_tags:
                    v = (t.get("value") or "").strip()
                    if v:
                        tags_parts.append(v)
                # 2. 事件元数据 (新版本上线, 162860人预约)
                if sub_event_title:
                    tags_parts.append(sub_event_title)
                reserve_count = stat.get("reserve_count", 0)
                if reserve_count and reserve_count > 0:
                    tags_parts.append(f"{reserve_count}人预约")
                download_count = ", ".join(tags_parts)

                # ── 活动描述 ──
                activity_desc = sub_event_title or ""

                items.append({
                    "icon_url": icon_url,
                    "app_name": app_name,
                    "package_name": pkg,
                    "detail_url": f"https://www.taptap.cn/app/{game_id}",
                    "download_count": download_count,
                    "version_name": score,
                    "version_code": "",
                    "updated_at": target_date.strftime("%Y-%m-%d"),
                    "activity_desc": activity_desc,
                    "status_badge": sub_event_title,
                    "game_status": game_status,
                })

        # 请求间延迟
        await asyncio.sleep(0.5)

    logger.info("TapTap API 扫描完成: {} 天成功, 提取 {} 个新游戏",
                api_success_count, len(items))

    # ── 降级: API 完全失败时回退到 JSON-LD ──
    if api_success_count == 0:
        logger.warning("TapTap API 全部失败，降级到 HTML JSON-LD 解析")
        fallback_items = await _fetch_taptap_fallback_jsonld(existing, seen_pkgs)
        if not fallback_items:
            raise RuntimeError("TapTap API 和 JSON-LD 降级均无数据（站点可能异常或 IP 被封）")
        logger.info("TapTap JSON-LD 降级成功: {} 个游戏", len(fallback_items))
        return fallback_items

    return items


async def _fetch_taptap_fallback_jsonld(
    existing: set[str], seen_pkgs: set[str]
) -> list[dict]:
    """降级方案: 从 TapTap HTML 的 JSON-LD Event 中提取游戏 (旧逻辑)."""
    settings = get_settings()
    url = "https://www.taptap.cn/app-calendar"
    items: list[dict] = []

    try:
        status, html = await http_get(url, timeout=settings.request_timeout)
    except Exception as e:
        logger.warning("TapTap 降级 http_get 异常: {}", e)
        return items

    if status != 200 or len(html) < 500:
        return items

    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = _json_lib.loads(script.string)
            if not isinstance(data, dict) or data.get("@type") != "Event":
                continue
            name = data.get("name", "").strip()
            start = data.get("startDate", "")[:10]
            href = data.get("url", "") or ""
            image = data.get("image", "") or ""
            if not name or not start:
                continue

            app_id = ""
            m = re.search(r'/app/(\d+)', href)
            if m:
                app_id = m.group(1)
            pkg = f"taptap_{app_id}" if app_id else f"taptap_{slugify(name)}"

            if pkg in seen_pkgs or pkg in existing:
                continue
            seen_pkgs.add(pkg)

            updated_at = _parse_chinese_date(start) or start
            if image and not image.startswith("http") and image.startswith("//"):
                image = f"https:{image}"

            items.append({
                "icon_url": image,
                "app_name": name,
                "package_name": pkg,
                "detail_url": href if href.startswith("http") else f"https://www.taptap.cn{href}" if href.startswith("/") else "",
                "download_count": (data.get("description") or "")[:200],
                "version_name": "",
                "version_code": "",
                "updated_at": updated_at,
                "activity_desc": "",
                "status_badge": "",
                "game_status": "",
            })
        except (_json_lib.JSONDecodeError, TypeError, AttributeError):
            continue

    logger.info("TapTap JSON-LD 降级提取: {} 个游戏", len(items))
    return items


# ── 调试 HTML 保存 ─────────────────────────────────────────

def _save_debug_html(source: str, html: str):
    """保存 HTML 样本用于排查页面结构变化."""
    try:
        from pathlib import Path
        debug_dir = Path("./debug")
        debug_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = debug_dir / f"{source}_{timestamp}.html"
        fname.write_text(html[:500000], encoding="utf-8")  # 最多 500KB
        logger.debug("HTML 样本已保存: {}", fname)
    except Exception as e:
        logger.debug("保存 HTML 样本失败: {}", e)


# ── 数据库操作 ─────────────────────────────────────────────

def _load_existing_packages(source: str) -> set[str]:
    """从数据库加载某源已有的包名集合（用于增量提前终止）."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT package_name FROM daily_updates WHERE source = ?", (source,)
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


async def save_updates(source: str, items: list[dict]) -> None:
    """全量入库 — 先删后插 (用于全量刷新)."""
    if not items:
        logger.info("{} 无数据，跳过保存", source)
        return

    settings = get_settings()
    _source_max_map = {
        "3839": "display_limit_3839",
        "taptap": "display_limit_taptap",
    }
    max_items = getattr(settings, _source_max_map.get(source, "panel_max_items"), 200)

    def _sync() -> None:
        conn = get_connection()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM daily_updates WHERE source = ?", (source,))
            for item in items[:max_items]:
                conn.execute(
                    """INSERT INTO daily_updates
                       (source, icon_url, detail_url, app_name, package_name,
                        download_count, version_name, version_code, updated_at,
                        activity_desc, status_badge, game_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source,
                     item.get("icon_url", ""),
                     item.get("detail_url", ""),
                     item.get("app_name", ""),
                     item["package_name"],
                     item.get("download_count", ""),
                     item.get("version_name", ""),
                     item.get("version_code", ""),
                     item.get("updated_at"),
                     item.get("activity_desc", ""),
                     item.get("status_badge", ""),
                     item.get("game_status", "")),
                )
            # 清理前天之前的历史数据（只保留昨天及以后）
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            conn.execute(
                "DELETE FROM daily_updates WHERE source = ? AND updated_at < ?",
                (source, yesterday),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    await asyncio.to_thread(_sync)
    logger.info("{} 全量保存: {} 条 (max={})", source, min(len(items), max_items), max_items)


async def save_incremental(source: str, items: list[dict]) -> None:
    """增量追加入库 — INSERT OR REPLACE 合并, 超限自动删旧."""
    if not items:
        logger.info("{} 无新数据", source)
        return

    settings = get_settings()
    _source_max_map = {
        "3839": "display_limit_3839",
        "taptap": "display_limit_taptap",
    }
    max_items = getattr(settings, _source_max_map.get(source, "panel_max_items"), 200)

    def _sync() -> None:
        conn = get_connection()
        try:
            conn.execute("BEGIN")
            for item in items:
                conn.execute(
                    """INSERT OR REPLACE INTO daily_updates
                       (source, icon_url, detail_url, app_name, package_name,
                        download_count, version_name, version_code, updated_at,
                        activity_desc, status_badge, game_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source,
                     item.get("icon_url", ""),
                     item.get("detail_url", ""),
                     item.get("app_name", ""),
                     item["package_name"],
                     item.get("download_count", ""),
                     item.get("version_name", ""),
                     item.get("version_code", ""),
                     item.get("updated_at"),
                     item.get("activity_desc", ""),
                     item.get("status_badge", ""),
                     item.get("game_status", "")),
                )
            # 清理超过数量上限的旧记录
            conn.execute("""
                DELETE FROM daily_updates WHERE source = ? AND id NOT IN (
                    SELECT id FROM daily_updates WHERE source = ?
                    ORDER BY updated_at DESC LIMIT ?
                )
            """, (source, source, max_items))
            # 清理前天之前的历史数据（只保留昨天及以后）
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            conn.execute(
                "DELETE FROM daily_updates WHERE source = ? AND updated_at < ?",
                (source, yesterday),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    await asyncio.to_thread(_sync)
    logger.info("{} 增量保存: {} 条 (max={})", source, len(items), max_items)


# ── 熔断器 ─────────────────────────────────────────────────

async def is_circuit_open(source: str) -> bool:
    def _sync():
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT is_open, open_until FROM daily_updates_circuit_breaker WHERE source = ?",
                (source,),
            )
            row = cur.fetchone()
            if row and row[0] and row[1]:
                open_until = datetime.fromisoformat(row[1])
                if datetime.now() < open_until:
                    return True
                conn.execute(
                    "UPDATE daily_updates_circuit_breaker SET is_open=0, consecutive_failures=0, open_until=NULL WHERE source=?",
                    (source,),
                )
                conn.commit()
        finally:
            conn.close()
        return False
    return await asyncio.to_thread(_sync)


async def record_failure(source: str, weight: int = 1):
    """记录失败, 支持权重 (CF 失败权重 2×)."""
    def _sync():
        conn = get_connection()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """INSERT INTO daily_updates_circuit_breaker
                   (source, consecutive_failures, last_failure_time, is_open, open_until)
                   VALUES (?, ?, ?, 0, NULL)
                   ON CONFLICT(source) DO UPDATE SET
                   consecutive_failures = consecutive_failures + ?, last_failure_time = ?""",
                (source, weight, weight, now),
            )
            conn.commit()
            cur = conn.execute(
                "SELECT consecutive_failures FROM daily_updates_circuit_breaker WHERE source=?",
                (source,),
            )
            row = cur.fetchone()
            if row:
                if row[0] >= 2:
                    settings = get_settings()
                    current = getattr(settings, "update_check_interval", 3600)
                    if current < 7200:
                        try:
                            settings.update({"update_check_interval": 7200})
                        except ValueError:
                            pass
                        logger.warning("source {} 连续失败 {} 次, 自动降频至 7200s", source, row[0])
                if row[0] >= 3:
                    open_until = (datetime.now() + timedelta(minutes=30)).isoformat()
                    conn.execute(
                        "UPDATE daily_updates_circuit_breaker SET is_open=1, open_until=? WHERE source=?",
                        (open_until, source),
                    )
                    conn.commit()
                    logger.warning("source {} 连续失败 {} 次, 熔断 30min", source, row[0])
        finally:
            conn.close()
    await asyncio.to_thread(_sync)


async def record_cf_failure(source: str):
    """CF 特定失败 — 2× 权重加速降频/熔断."""
    logger.warning("source {} hit Cloudflare block, fast-tracking cooldown", source)
    await record_failure(source, weight=2)


async def record_success(source: str):
    def _sync():
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO daily_updates_circuit_breaker
                   (source, consecutive_failures, is_open, open_until)
                   VALUES (?, 0, 0, NULL)
                   ON CONFLICT(source) DO UPDATE SET
                   consecutive_failures=0, is_open=0, open_until=NULL""",
                (source,),
            )
            conn.commit()
        finally:
            conn.close()
    await asyncio.to_thread(_sync)
    # 成功率恢复后恢复默认间隔
    settings = get_settings()
    current = getattr(settings, "update_check_interval", 3600)
    if current > 3600:
        try:
            settings.update({"update_check_interval": 3600})
        except ValueError:
            pass
        logger.info("source {} 恢复成功, 更新间隔恢复为 3600s", source)


# ── 编排 ──────────────────────────────────────────────────

async def fetch_source_with_circuit_breaker(source: str, full_refresh: bool = False):
    """带熔断的源抓取."""
    if await is_circuit_open(source):
        logger.warning("source {} circuit open, skipping", source)
        add_log(source, "circuit_open", "熔断保护中，已跳过")
        return

    add_log(source, "start", "全量刷新" if full_refresh else "增量刷新")
    try:
        fn_map = {
            "3839": fetch_3839_updates,
            "taptap": fetch_taptap_updates,
        }
        items = await fn_map[source](full_refresh=full_refresh)

        if not items:
            if full_refresh:
                raise Exception(f"{source} 全量刷新返回空数据（站点可能异常）")
            logger.info("{} 无新数据", source)
            add_log(source, "done", "无新数据")
            await record_success(source)
            return

        if full_refresh:
            await save_updates(source, items)
        else:
            await save_incremental(source, items)

        add_log(source, "done", f"获取 {len(items)} 条")
        await record_success(source)
    except Exception as e:
        logger.error("fetch {} failed: {}", source, e)
        add_log(source, "error", str(e)[:100])
        await record_failure(source)


async def update_once(full_refresh: bool = False, sources: list[str] | None = None):
    """执行一次更新周期.

    Args:
        full_refresh: True=全量刷新, False=增量刷新
        sources: 指定刷新的源列表, None=全部源
    """
    all_sources = ["3839", "taptap"]
    targets = [s for s in (sources or all_sources) if s in all_sources]
    if not targets:
        return
    await asyncio.gather(
        *(fetch_source_with_circuit_breaker(s, full_refresh=full_refresh) for s in targets),
        return_exceptions=True,
    )
    set_last_modified(datetime.now(timezone.utc))


async def run_periodic_updates():
    """定时循环 — 每小时增量刷新."""
    while True:
        settings = get_settings()
        interval = getattr(settings, "update_check_interval", 3600)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        try:
            await update_once(full_refresh=False)
            logger.info("定时增量刷新完成")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("定时刷新异常: {}", e)
