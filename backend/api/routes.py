"""REST API 路由 — 每日新游面板 + 配置 + 刷新."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime, format_datetime
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.responses import JSONResponse, Response

from backend.api.websocket import get_ws_manager
from backend.config import get_settings, reload_settings
from backend.db.database import get_connection
from backend.logging_setup import get_logger

logger = get_logger()

router = APIRouter(prefix="/api")

# ── 所有支持的国内源 ─────────────────────────────────────────
_ALL_SOURCES = {"3839", "taptap"}

# ── 刷新状态锁 ─────────────────────────────────────────────
_refreshing_sources: set[str] = set()
_refresh_lock = asyncio.Lock()


# ── 健康检查 ───────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/test-proxy")
async def test_proxy():
    """测试代理连通性."""
    import time
    from backend.core.http_client import http_get

    settings = get_settings()
    effective_proxy = settings.domestic_proxy or settings.proxy
    if not effective_proxy:
        return {"ok": False, "error": "未配置代理"}

    test_url = "https://www.baidu.com"
    start = time.time()
    try:
        status, html = await http_get(test_url)
        latency = round((time.time() - start) * 1000)
        if status == 200 and len(html) > 200:
            return {"ok": True, "latency_ms": latency}
        return {"ok": False, "error": f"HTTP {status}", "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": round((time.time() - start) * 1000)}


# ── 每日更新面板 ───────────────────────────────────────────

@router.get("/daily-updates")
async def daily_updates(
    request: Request,
    source: str = Query(None),
    limit: int = Query(20),
):
    """获取国内新游列表, 支持条件请求."""
    from backend.cron.domestic_tracker import get_last_modified

    # 条件请求 (RFC 7231)
    last_mod = get_last_modified()
    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since and last_mod:
        try:
            client_time = parsedate_to_datetime(if_modified_since)
            if client_time >= last_mod:
                return Response(status_code=304)
        except (ValueError, TypeError, LookupError):
            pass

    settings = get_settings()

    _display_limits = {
        "3839": getattr(settings, "display_limit_3839", 60),
        "taptap": getattr(settings, "display_limit_taptap", 60),
    }

    conn = get_connection()
    try:
        result: dict = {}
        for src in _ALL_SOURCES:
            if source and source != src:
                continue
            src_limit = _display_limits.get(src, limit)
            rows = conn.execute(
                """SELECT app_name, icon_url, detail_url, package_name,
                   download_count, version_name, updated_at,
                   activity_desc, status_badge, game_status
                   FROM daily_updates WHERE source = ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (src, src_limit),
            ).fetchall()
            result[src] = [
                {
                    "app_name": r["app_name"],
                    "icon_url": r["icon_url"] or "",
                    "detail_url": r["detail_url"] or "",
                    "package_name": r["package_name"],
                    "download_count": r["download_count"] or "",
                    "version_name": r["version_name"] or "",
                    "updated_at": r["updated_at"],
                    "activity_desc": r["activity_desc"] or "",
                    "status_badge": r["status_badge"] or "",
                    "game_status": r["game_status"] or "",
                }
                for r in rows
            ]
    finally:
        conn.close()

    result["poll_interval"] = getattr(settings, "frontend_poll_interval", 300)
    if last_mod:
        beijing_time = last_mod + timedelta(hours=8)
        result["last_fetched_at"] = beijing_time.strftime("%Y-%m-%d %H:%M:%S")

    headers = {}
    if last_mod:
        headers["Last-Modified"] = format_datetime(last_mod, usegmt=True)
    return JSONResponse(content=result, headers=headers)


# ── 刷新端点 ───────────────────────────────────────────────

def _parse_sources(body: dict[str, Any] | None) -> list[str]:
    """从请求体中解析 sources 参数, 未提供则返回全部源."""
    if body and isinstance(body.get("sources"), list):
        sources = [s for s in body["sources"] if s in _ALL_SOURCES]
        if sources:
            return sources
    return list(_ALL_SOURCES)


@router.post("/daily-updates/refresh")
async def trigger_daily_refresh(body: dict[str, Any] | None = None):
    """fire-and-forget: 立即返回, 后台全量刷新.

    可选 body: {"sources": ["3839"]} — 仅刷新指定源
    """
    global _refreshing_sources
    from backend.cron.domestic_tracker import update_once

    sources = _parse_sources(body)
    target_set = set(sources)

    async with _refresh_lock:
        conflict = target_set & _refreshing_sources
        if conflict:
            return {"status": "busy", "sources": list(conflict), "message": "部分源正在刷新中，请稍后再试"}
        _refreshing_sources |= target_set

    async def _run():
        global _refreshing_sources
        try:
            await update_once(full_refresh=True, sources=sources)
            logger.info("全量刷新完成: {}", sources)
        except Exception as e:
            logger.error("全量刷新失败: {}", e)
        finally:
            async with _refresh_lock:
                _refreshing_sources -= target_set

    asyncio.create_task(_run())
    return {"status": "started", "sources": sources, "message": f"全量刷新已启动 ({len(sources)} 个源)，后台执行中"}


@router.post("/daily-updates/refresh-incremental")
async def trigger_incremental_refresh(body: dict[str, Any] | None = None):
    """fire-and-forget: 立即返回, 后台增量刷新."""
    global _refreshing_sources
    from backend.cron.domestic_tracker import update_once

    sources = _parse_sources(body)
    target_set = set(sources)

    async with _refresh_lock:
        conflict = target_set & _refreshing_sources
        if conflict:
            return {"status": "busy", "sources": list(conflict), "message": "部分源正在刷新中，请稍后再试"}
        _refreshing_sources |= target_set

    async def _run():
        global _refreshing_sources
        try:
            await update_once(full_refresh=False, sources=sources)
            logger.info("增量刷新完成: {}", sources)
        except Exception as e:
            logger.error("增量刷新失败: {}", e)
        finally:
            async with _refresh_lock:
                _refreshing_sources -= target_set

    asyncio.create_task(_run())
    return {"status": "started", "sources": sources, "message": f"增量刷新已启动 ({len(sources)} 个源)，后台执行中"}


@router.get("/daily-updates/refresh-status")
async def refresh_status():
    """查询刷新任务是否正在运行."""
    return {"running": len(_refreshing_sources) > 0, "sources": list(_refreshing_sources)}


# ── 配置 ───────────────────────────────────────────────────

@router.get("/config")
async def config_get():
    settings = get_settings()
    return settings.model_dump(exclude_none=True)


@router.patch("/config")
async def config_update(data: dict[str, Any]):
    settings = get_settings()
    try:
        settings.update(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    reload_settings()
    return {"ok": True}


# ── 爬虫事件日志 ───────────────────────────────────────────

@router.get("/crawl-log")
async def crawl_log(limit: int = 20):
    """获取最近的爬虫事件日志."""
    from backend.cron.domestic_tracker import get_crawl_log
    entries = get_crawl_log(limit)
    # 附加当前刷新状态
    return {
        "entries": entries,
        "refreshing": list(_refreshing_sources),
    }


# ── 手动解封 ───────────────────────────────────────────────

@router.post("/unblock")
async def unblock_source(request: Request, body: dict[str, Any] | None = None):
    """手动重置指定源的熔断器 (仅允许本地访问)."""
    if request.client and request.client.host != "127.0.0.1":
        raise HTTPException(403, "仅允许本地访问")

    source = body.get("source", "") if body else ""
    if source not in _ALL_SOURCES:
        raise HTTPException(400, f"无效的源标识: {source}")

    from backend.cron.domestic_tracker import record_success as _reset
    await _reset(source)
    logger.info("{} 熔断器已被管理员手动重置", source)
    return {"ok": True, "message": f"{source} 熔断器已重置"}


# ── WebSocket ──────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_global(websocket: WebSocket):
    """全局 WebSocket：接收刷新通知."""
    ws_mgr = get_ws_manager()
    await ws_mgr.connect(websocket)
    try:
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_mgr.disconnect(websocket)
