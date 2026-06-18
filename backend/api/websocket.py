"""WebSocket 管理器 — 全局广播 + 任务订阅."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket
from backend.logging_setup import get_logger

logger = get_logger()


class WebSocketManager:
    """管理 WebSocket 连接，支持广播和按 task_id 推送."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}  # key: 连接 id
        self._task_subscribers: dict[str, list[str]] = {}  # task_id → [conn_id, ...]
        self._counter = 0

    async def connect(self, websocket: WebSocket, task_id: str | None = None):
        """接受 WebSocket 连接."""
        await websocket.accept()
        conn_id = f"ws_{self._counter}"
        self._counter += 1
        self._connections[conn_id] = websocket
        if task_id:
            self._task_subscribers.setdefault(task_id, []).append(conn_id)
        logger.debug("WebSocket 连接: {} (task={})", conn_id, task_id)

    def disconnect(self, websocket: WebSocket, task_id: str | None = None):
        """断开 WebSocket 连接."""
        to_remove = [cid for cid, ws in self._connections.items() if ws is websocket]
        for cid in to_remove:
            del self._connections[cid]
            for subs in self._task_subscribers.values():
                if cid in subs:
                    subs.remove(cid)

    async def broadcast(self, message: dict[str, Any]):
        """向所有连接广播消息."""
        dead = []
        for cid, ws in list(self._connections.items()):
            try:
                await ws.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._connections.pop(cid, None)

    async def send_to_task(self, task_id: str, message: dict[str, Any]):
        """向订阅特定 task_id 的连接发送消息."""
        subs = list(self._task_subscribers.get(task_id, []))
        dead = []
        for cid in subs:
            ws = self._connections.get(cid)
            if ws:
                try:
                    await ws.send_text(json.dumps(message, ensure_ascii=False))
                except Exception:
                    dead.append(cid)
        for cid in dead:
            self._connections.pop(cid, None)
            if cid in subs:
                subs.remove(cid)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


# 全局单例
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
