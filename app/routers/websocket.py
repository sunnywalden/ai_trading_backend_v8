"""V9: WebSocket 连接管理器 + 路由"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError

from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)
_shutdown_event = asyncio.Event()


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        async with self._lock:
            # 同一用户只保留最新连接
            old = self._connections.get(user_id)
            if old:
                try:
                    await old.close()
                except Exception:
                    pass
            self._connections[user_id] = websocket
        print(f"[WS] Connected: {user_id}, total: {len(self._connections)}")

    async def disconnect(self, user_id: str):
        async with self._lock:
            self._connections.pop(user_id, None)
        print(f"[WS] Disconnected: {user_id}, total: {len(self._connections)}")

    async def send_personal(self, user_id: str, event: str, data: dict):
        ws = self._connections.get(user_id)
        if ws:
            try:
                await ws.send_json({"event": event, "data": data, "ts": datetime.utcnow().isoformat()})
            except Exception:
                await self.disconnect(user_id)

    async def broadcast(self, event: str, data: dict):
        """广播给所有连接"""
        msg = json.dumps({"event": event, "data": data, "ts": datetime.utcnow().isoformat()})
        dead = []
        for uid, ws in list(self._connections.items()):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(uid)
        for uid in dead:
            await self.disconnect(uid)

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def close_all(self, *, code: int = 1012, reason: str = "Server reload") -> None:
        async with self._lock:
            connections = list(self._connections.items())
            self._connections.clear()

        for user_id, ws in connections:
            try:
                await ws.close(code=code, reason=reason)
            except Exception:
                pass
            print(f"[WS] Disconnected: {user_id}, total: {len(self._connections)}")


# 全局实例
manager = ConnectionManager()


def _verify_ws_token(token: str) -> Optional[str]:
    """验证 WebSocket Token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None


def mark_shutdown_started() -> None:
    _shutdown_event.set()


def reset_shutdown_state() -> None:
    _shutdown_event.clear()


async def close_all_websockets() -> None:
    mark_shutdown_started()
    await asyncio.gather(
        manager.close_all(),
        sa_manager.close_all(),
        return_exceptions=True,
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket 端点：认证后建立长连接"""
    user_id = _verify_ws_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, user_id)
    try:
        while not _shutdown_event.is_set():
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            # 处理客户端心跳
            if data == "ping":
                await websocket.send_text("pong")
            else:
                # 其他消息可扩展
                pass
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    except asyncio.CancelledError:
        await manager.disconnect(user_id)
        raise
    except Exception:
        await manager.disconnect(user_id)


# ── V10.3: 态势感知 WebSocket ─────────────────────────────────────────────────
class _SAConnectionManager:
    """态势感知专用 WebSocket 连接管理器（匿名广播，无需用户 ID）。"""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)

    async def broadcast(self, payload: dict):
        msg = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def close_all(self, *, code: int = 1012, reason: str = "Server reload") -> None:
        async with self._lock:
            connections = list(self._connections)
            self._connections.clear()

        for ws in connections:
            try:
                await ws.close(code=code, reason=reason)
            except Exception:
                pass


sa_manager = _SAConnectionManager()


@router.websocket("/ws/situational-awareness")
async def sa_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    interval: int = Query(3, ge=2, le=30, description="推送间隔秒"),
):
    """V10.3 态势感知 WebSocket：每 interval 秒检测状态变化并推送。"""
    user_id = _verify_ws_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await sa_manager.connect(websocket)
    try:
        from app.models.db import SessionLocal
        from app.services.situational_awareness_service import situational_awareness_service
        from app.schemas.situational_awareness import SituationalAwarenessSnapshot

        prev_snapshot: Optional[SituationalAwarenessSnapshot] = None

        while not _shutdown_event.is_set():
            try:
                async with SessionLocal() as db:
                    snapshot = await situational_awareness_service.get_snapshot(db)

                if situational_awareness_service.has_changed(prev_snapshot, snapshot):
                    await websocket.send_json({
                        "type": "sa_update",
                        "data": snapshot.model_dump(mode="json"),
                    })
                    prev_snapshot = snapshot

            except Exception as exc:
                if _shutdown_event.is_set():
                    break
                try:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                except Exception:
                    break

            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        await sa_manager.disconnect(websocket)
