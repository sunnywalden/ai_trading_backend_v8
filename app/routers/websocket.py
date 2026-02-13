"""V9: WebSocket 连接管理器 + 路由"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError

from app.core.config import settings

router = APIRouter()


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


# 全局实例
manager = ConnectionManager()


def _verify_ws_token(token: str) -> Optional[str]:
    """验证 WebSocket Token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket 端点：认证后建立长连接"""
    user_id = _verify_ws_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            # 处理客户端心跳
            if data == "ping":
                await websocket.send_text("pong")
            else:
                # 其他消息可扩展
                pass
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    except Exception:
        await manager.disconnect(user_id)
