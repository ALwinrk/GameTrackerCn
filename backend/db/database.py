"""SQLite 数据库连接 + 建表."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


DB_DIR = Path("./data")
DB_PATH = DB_DIR / "crawler.db"

_local = threading.local()
_all_connections: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """获取当前线程的 SQLite 连接（线程安全）."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.execute("PRAGMA busy_timeout=3000")
        with _conn_lock:
            _all_connections.append(_local.conn)
    else:
        try:
            _local.conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.InterfaceError):
            _local.conn = None
            return get_connection()
    return _local.conn


def init_db() -> None:
    """创建所有表."""
    conn = get_connection()

    # 每日更新面板
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            app_name TEXT,
            icon_url TEXT DEFAULT '',
            detail_url TEXT DEFAULT '',
            package_name TEXT NOT NULL,
            download_count TEXT DEFAULT '',
            version_name TEXT,
            version_code TEXT DEFAULT '',
            updated_at TIMESTAMP,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 兼容：新增列
    for col, col_type in [
        ("icon_url", "TEXT DEFAULT ''"),
        ("detail_url", "TEXT DEFAULT ''"),
        ("download_count", "TEXT DEFAULT ''"),
        ("activity_desc", "TEXT DEFAULT ''"),
        ("status_badge", "TEXT DEFAULT ''"),
        ("game_status", "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE daily_updates ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # 唯一索引 — 支持 INSERT OR REPLACE 去重 (同一游戏可在不同日期各有一行)
    try:
        conn.execute("DROP INDEX IF EXISTS idx_source_package")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DROP INDEX IF EXISTS idx_source_package_date")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_source_package_date
        ON daily_updates(source, package_name, updated_at)
    """)

    # 熔断器
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_updates_circuit_breaker (
            source TEXT PRIMARY KEY,
            consecutive_failures INTEGER DEFAULT 0,
            last_failure_time TIMESTAMP,
            is_open BOOLEAN DEFAULT 0,
            open_until TIMESTAMP
        )
    """)

    conn.commit()


def close_db() -> None:
    """关闭所有数据库连接."""
    with _conn_lock:
        for conn in _all_connections:
            try:
                conn.close()
            except Exception:
                pass
        _all_connections.clear()
    if hasattr(_local, "conn") and _local.conn:
        _local.conn = None
