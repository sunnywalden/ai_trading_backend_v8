"""V9: 通知服务"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notification import NotificationLog


class NotificationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def send(
        self,
        account_id: str,
        channel: str,
        event_type: str,
        title: str,
        body: Optional[str] = None,
    ) -> bool:
        """发送通知并记录"""
        success = False

        if channel == "websocket":
            success = await self._send_websocket(event_type, title, body)
        elif channel == "telegram":
            success = await self._send_telegram(title, body)
        elif channel == "desktop":
            success = True  # 前端处理
        else:
            print(f"[Notification] Unknown channel: {channel}")

        # 记录日志
        log = NotificationLog(
            account_id=account_id,
            channel=channel,
            event_type=event_type,
            title=title,
            body=body,
            status="SENT" if success else "FAILED",
        )
        self.session.add(log)
        try:
            await self.session.commit()
        except Exception:
            pass

        return success

    async def broadcast(self, account_id: str, event_type: str, title: str, body: Optional[str] = None):
        """广播到所有启用的通道"""
        channels = ["websocket"]
        if getattr(settings, 'TELEGRAM_BOT_TOKEN', None):
            channels.append("telegram")
        for ch in channels:
            await self.send(account_id, ch, event_type, title, body)

    async def _send_websocket(self, event_type: str, title: str, body: Optional[str]) -> bool:
        """通过 WebSocket 推送"""
        try:
            from app.routers.websocket import manager
            await manager.broadcast(event_type, {
                "title": title,
                "body": body,
                "timestamp": datetime.utcnow().isoformat(),
            })
            return True
        except Exception as e:
            print(f"[Notification] WebSocket send failed: {e}")
            return False

    async def _send_telegram(self, title: str, body: Optional[str]) -> bool:
        """通过 Telegram 推送"""
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)
        if not token or not chat_id:
            return False

        try:
            import httpx
            message = f"🔔 {title}"
            if body:
                message += f"\n\n{body}"
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            print(f"[Notification] Telegram send failed: {e}")
            return False
