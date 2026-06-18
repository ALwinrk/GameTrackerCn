"""国内游戏每日新游排查系统 — FastAPI 主应用.

精简版架构（对比海外版）:
- ✅ 每日新游面板 (好游快爆 + TapTap)
- ✅ 定时抓取 + 熔断保护
- ✅ 前端 SPA 静态文件服务
- ❌ 单包名查询（不需要）
- ❌ 批量 Excel 处理（不需要）
- ❌ 下载管理器（不需要）
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.api.routes import router
from backend.config import get_settings
from backend.db.database import init_db, close_db
from backend.logging_setup import setup_logging, get_logger


# ── 浏览器就绪事件 ────────────────────────────────────────
browser_ready = asyncio.Event()
browser_failed = asyncio.Event()


# ── 强制退出 ──────────────────────────────────────────────

_force_exit = False


def _do_force_exit():
    global _force_exit
    if _force_exit:
        return
    _force_exit = True
    try:
        print("[v1.0] 收到退出信号，强制关闭...")
        loop = asyncio.get_running_loop()
        tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
    except Exception:
        pass
    os._exit(0)


def setup_console_handler():
    """注册 Windows 控制台关闭事件 + Unix 信号处理."""
    if sys.platform == "win32":
        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        def _handler(ctrl_type):
            if ctrl_type == 2:  # CTRL_CLOSE_EVENT
                _do_force_exit()
                return True
            return False
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)
    else:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: _do_force_exit())


# ── 生命周期 ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理."""
    # ── 启动 ──
    settings = get_settings()
    setup_logging(
        log_dir="./logs",
        level=settings.log_level,
        retention=settings.log_retention_days,
    )
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("国内游戏每日新游排查系统 v1.1 启动中...")
    logger.info("=" * 60)

    # 数据库
    init_db()
    logger.info("SQLite 数据库已初始化: data/crawler.db")

    # 浏览器管理器（后台初始化，不阻塞服务启动）
    browser_task = None

    async def _init_browser_background():
        try:
            from backend.core.browser_manager import get_browser_manager
            mgr = get_browser_manager()
            await mgr.start()
            browser_ready.set()
            logger.info("Playwright 浏览器就绪")
        except asyncio.CancelledError:
            raise  # 重新抛出, 让外层 asyncio.gather(return_exceptions=True) 处理
        except Exception as e:
            logger.warning("浏览器初始化失败 (TapTap 动态渲染不可用): {}", e)
            browser_failed.set()
            browser_ready.set()

    browser_task = asyncio.create_task(_init_browser_background())

    # 定时更新任务
    from backend.db.database import get_connection
    from backend.cron.domestic_tracker import run_periodic_updates

    has_data = False
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM daily_updates").fetchone()[0]
        has_data = count > 0
    finally:
        conn.close()

    update_task = asyncio.create_task(run_periodic_updates())

    if has_data:
        logger.info("已有缓存数据 ({} 条), 面板立即可用", count)
    else:
        logger.info("数据库无缓存数据，请手动点击「全量刷新」开始爬取")

    logger.info("代理: {}", settings.domestic_proxy or settings.proxy or "直连")
    logger.info("启用站点: 好游快爆={}, TapTap={}", settings.enable_3839, settings.enable_taptap)
    logger.info("服务就绪 — 前端可访问 http://127.0.0.1:8001")

    yield

    # ── 关闭 ──
    logger.info("正在关闭...")
    update_task.cancel()
    if browser_task:
        browser_task.cancel()
    await asyncio.gather(*[t for t in (update_task, browser_task) if t is not None], return_exceptions=True)

    # 关闭浏览器
    try:
        from backend.core.browser_manager import get_browser_manager
        await get_browser_manager().stop()
    except Exception:
        pass

    close_db()
    logger.info("系统已关闭")


# ── FastAPI 应用 ──────────────────────────────────────────

app = FastAPI(
    title="国内游戏每日新游排查系统",
    description="好游快爆 + TapTap 新游预约/上线监控面板",
    version="1.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)


# ── 健康检查 ──────────────────────────────────────────────

@app.get("/api/ready")
async def ready():
    if browser_failed.is_set():
        return {"status": "ready", "browser_available": False}
    if not browser_ready.is_set():
        return {"status": "loading"}
    return {"status": "ready", "browser_available": True}


# ── 静态文件 (Vue3 前端) ───────────────────────────────────

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = FRONTEND_DIST / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}

    get_logger().info("前端静态文件已挂载: {}", FRONTEND_DIST)


# ── 直接启动入口 ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # v1.1: 确保工作目录为项目根 (与 launcher.py 行为一致)
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    setup_console_handler()
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8001,
        timeout_graceful_shutdown=2,
        log_level="info",
    )
