"""V10.5.4: SignalTransitionService — 信号状态迁移元数据服务。

目标：在不引入新表迁移的前提下，为 TradingSignal.extra_metadata 提供
统一、可复用的原生状态迁移记录格式，并保留旧的 status_history 兼容字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class SignalTransitionService:
    """统一维护信号原生状态迁移记录。"""

    MAX_STATUS_HISTORY = 20
    MAX_SIGNAL_TRANSITIONS = 50

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def append_transition(
        cls,
        meta: dict[str, Any] | None,
        *,
        from_status: str,
        to_status: str,
        actor: str,
        stage: str | None = None,
        reason_code: str | None = None,
        reason_detail: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        payload = cls._safe_dict(meta).copy()
        at = datetime.utcnow().isoformat()

        legacy_history = payload.get("status_history")
        if not isinstance(legacy_history, list):
            legacy_history = []
        legacy_history.append(
            {
                "from": from_status,
                "to": to_status,
                "at": at,
                "reason": reason_code or reason_detail,
            }
        )
        payload["status_history"] = legacy_history[-cls.MAX_STATUS_HISTORY :]

        transitions = payload.get("signal_transitions")
        if not isinstance(transitions, list):
            transitions = []
        transitions.append(
            {
                "from_status": from_status,
                "to_status": to_status,
                "at": at,
                "actor": actor,
                "stage": stage,
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "correlation_id": correlation_id,
                "result_source": "NATIVE_TRANSITION_LOG",
            }
        )
        payload["signal_transitions"] = transitions[-cls.MAX_SIGNAL_TRANSITIONS :]
        payload["latest_transition"] = transitions[-1]
        return payload

    @classmethod
    def latest_transition(cls, meta: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = cls._safe_dict(meta)
        latest = payload.get("latest_transition")
        if isinstance(latest, dict):
            return latest
        transitions = payload.get("signal_transitions")
        if isinstance(transitions, list):
            for item in reversed(transitions):
                if isinstance(item, dict):
                    return item
        return None


signal_transition_service = SignalTransitionService()
