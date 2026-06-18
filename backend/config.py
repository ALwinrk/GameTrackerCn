"""配置管理 — pydantic BaseSettings + config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置，支持从 config.json 和环境变量读取."""

    # ── 代理 ──────────────────────────────
    proxy: str = "http://127.0.0.1:7897"
    domestic_proxy: str = ""       # 国内源独立代理（通常为空=直连）

    # ── 爬虫 ──────────────────────────────
    scraper_concurrency: int = 2   # 国内源并发数
    playwright_concurrency: int = 2
    retry_times: int = 2
    retry_delay: float = 1.0

    # ── HTTP 超时 ─────────────────────────
    request_timeout: float = 10.0
    stealth_timeout: float = 30.0  # Playwright 页面加载超时

    # ── 定时更新 ─────────────────────────
    update_check_interval: int = 3600    # 定时抓取间隔(秒), 默认1小时
    frontend_poll_interval: int = 300    # 前端轮询间隔(秒), 默认5分钟

    # ── 站点开关 ──────────────────────────
    enable_3839: bool = True
    enable_taptap: bool = True

    # ── 展示限制 ──────────────────────────
    display_limit_3839: int = 400
    display_limit_taptap: int = 200
    panel_max_items: int = 500           # 每源数据库保留上限

    # ── 日志 ──────────────────────────────
    log_level: str = "INFO"
    log_retention_days: int = 30

    # ── 系统公告 ──────────────────────────
    notice_enabled: bool = False
    notice_text: str = ""

    class Config:
        env_prefix = "CHINAGAME_"
        env_file = ".env"
        extra = "ignore"

    @classmethod
    def from_json(cls, path: str = "config.json") -> Settings:
        """从 config.json 加载配置.

        PyInstaller EXE 环境: 优先 CWD, 不存在时从 _MEIPASS 复制.
        """
        import sys
        config_path = Path(path)
        if not config_path.exists():
            # PyInstaller: 从 _MEIPASS 中复制默认配置到 CWD
            if getattr(sys, "frozen", False):
                meipass = Path(sys._MEIPASS)
                bundled = meipass / "config.json"
                if bundled.exists():
                    import shutil
                    shutil.copy(str(bundled), str(config_path))
                    config_path = Path(path)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        return cls()

    def save(self, path: str = "config.json") -> None:
        """保存配置到 config.json."""
        data = self.model_dump(exclude_none=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # 允许通过 /api/config PATCH 热更新的键白名单
    _HOT_UPDATE_WHITELIST: set[str] = {
        "proxy", "domestic_proxy",
        "scraper_concurrency", "playwright_concurrency",
        "retry_times", "retry_delay",
        "request_timeout", "stealth_timeout",
        "update_check_interval", "frontend_poll_interval",
        "enable_3839", "enable_taptap",
        "display_limit_3839", "display_limit_taptap",
        "panel_max_items",
        "log_level", "log_retention_days",
        "notice_enabled", "notice_text",
    }

    # 数值型配置键 (需要类型校验和范围校验)
    _NUMERIC_KEYS: set[str] = {
        "scraper_concurrency", "playwright_concurrency",
        "retry_times", "retry_delay",
        "request_timeout", "stealth_timeout",
        "update_check_interval", "frontend_poll_interval",
        "display_limit_3839", "display_limit_taptap",
        "panel_max_items",
    }

    def update(self, changes: dict[str, Any]) -> None:
        """运行时更新配置 — 仅白名单键可通过 API 修改, 非白名单键静默跳过."""
        for key, value in changes.items():
            if key not in self._HOT_UPDATE_WHITELIST or not hasattr(self, key):
                continue
            # 数值型字段: 类型转换 + 范围校验
            if key in self._NUMERIC_KEYS:
                try:
                    value = type(getattr(self, key))(value)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, (int, float)) and value < 0:
                    continue
            setattr(self, key, value)
        self.save()


# 全局单例
_settings: Settings | None = None


def get_settings(config_path: str = "config.json") -> Settings:
    """获取全局配置单例."""
    global _settings
    if _settings is None:
        _settings = Settings.from_json(config_path)
    return _settings


def reload_settings(config_path: str = "config.json") -> Settings:
    """重新加载配置."""
    global _settings
    _settings = Settings.from_json(config_path)
    return _settings
