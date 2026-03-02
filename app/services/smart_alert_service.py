"""smart_alert_service.py — V10.3.3 智能告警服务

功能：
1. AI 分级：CRITICAL / HIGH / MEDIUM / LOW
2. 相似告警自动合并（cosine similarity > 0.85）
3. 自动生成 recommended_action_text
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: float = 0.85
ALERT_RETENTION_DAYS: int = 7


# ─── 内存 Alert Store（生产环境可替换为 Redis / 独立表）──────────────────────

_alert_store: list[dict[str, Any]] = []
_alert_id_counter: int = 0


def _next_id() -> int:
    global _alert_id_counter
    _alert_id_counter += 1
    return _alert_id_counter


def _simple_vectorize(text: str) -> list[float]:
    """极简词频向量（生产用 embedding API 替换）。"""
    words = text.lower().split()
    vocab = sorted(set(words))
    freq = {w: words.count(w) for w in vocab}
    vector = [float(freq.get(w, 0)) for w in vocab]
    return vector


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度。向量维度不同时填充 0。"""
    max_len = max(len(a), len(b))
    a = a + [0.0] * (max_len - len(a))
    b = b + [0.0] * (max_len - len(b))
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x ** 2 for x in a))
    norm_b = math.sqrt(sum(x ** 2 for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _ai_grade_alert(alert_type: str, content: str, value: float | None) -> str:
    """简单规则分级（生产环境替换为 LLM 分级）。"""
    content_lower = content.lower()
    critical_keywords = ["crash", "circuit breaker", "margin call", "stop loss triggered", "halt", "bankruptcy"]
    high_keywords = ["correlation spike", "drawdown", "risk limit", "unusual volume", "flash"]
    if any(k in content_lower for k in critical_keywords):
        return "CRITICAL"
    if any(k in content_lower for k in high_keywords):
        return "HIGH"
    if value is not None and abs(value) > 5.0:
        return "HIGH"
    if value is not None and abs(value) > 2.0:
        return "MEDIUM"
    return "LOW"


def _generate_action_text(grade: str, alert_type: str, content: str) -> str:
    """自动生成推荐操作文本。"""
    if grade == "CRITICAL":
        return "IMMEDIATE ACTION REQUIRED: Review position and consider emergency exit. Check risk limits."
    if grade == "HIGH":
        return f"High priority: Review {alert_type} alert. Assess impact on portfolio and adjust position sizing."
    if grade == "MEDIUM":
        return f"Monitor closely: {alert_type} requires attention within next 30 minutes."
    return "Informational: Log and review at next opportunity."


class SmartAlertService:
    """智能告警管理：AI 分级 + 相似合并 + 推荐操作。"""

    def create_alert(
        self,
        *,
        user_id: str,
        alert_type: str,
        title: str,
        content: str,
        symbol: str | None = None,
        value: float | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """创建新告警（写内存 store）。"""
        grade = _ai_grade_alert(alert_type, content, value)
        action_text = _generate_action_text(grade, alert_type, content)

        # 相似度检查——自动合并
        content_vec = _simple_vectorize(title + " " + content)
        existing_similar = None
        for alert in _alert_store:
            if alert["user_id"] != user_id or alert["dismissed"]:
                continue
            existing_vec = _simple_vectorize(alert["title"] + " " + alert["content"])
            if _cosine_similarity(content_vec, existing_vec) >= SIMILARITY_THRESHOLD:
                existing_similar = alert
                break

        if existing_similar:
            existing_similar["merged_count"] = existing_similar.get("merged_count", 1) + 1
            existing_similar["last_seen"] = datetime.utcnow().isoformat()
            logger.debug("SmartAlert: merged into alert_id=%s", existing_similar["id"])
            return existing_similar

        alert = {
            "id": _next_id(),
            "user_id": user_id,
            "alert_type": alert_type,
            "title": title,
            "content": content,
            "symbol": symbol,
            "value": value,
            "grade": grade,
            "recommended_action_text": action_text,
            "metadata": metadata or {},
            "dismissed": False,
            "acknowledged": False,
            "merged_count": 1,
            "created_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
        }
        _alert_store.append(alert)
        return alert

    def get_alerts(
        self,
        user_id: str,
        grade_filter: str | None = None,
        include_dismissed: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """返回告警列表，按 grade 优先级降序。"""
        grade_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        # 清理过期
        cutoff = (datetime.utcnow() - timedelta(days=ALERT_RETENTION_DAYS)).isoformat()
        active = [
            a for a in _alert_store
            if a["user_id"] == user_id
            and a["created_at"] >= cutoff
            and (include_dismissed or not a["dismissed"])
        ]
        if grade_filter:
            active = [a for a in active if a["grade"] == grade_filter]
        active.sort(key=lambda x: grade_order.get(x["grade"], 0), reverse=True)
        return active[:limit]

    def acknowledge_alert(self, user_id: str, alert_id: int) -> dict[str, Any] | None:
        for alert in _alert_store:
            if alert["id"] == alert_id and alert["user_id"] == user_id:
                alert["acknowledged"] = True
                return alert
        return None

    def dismiss_alert(self, user_id: str, alert_id: int) -> dict[str, Any] | None:
        for alert in _alert_store:
            if alert["id"] == alert_id and alert["user_id"] == user_id:
                alert["dismissed"] = True
                return alert
        return None

    def get_alert_stats(self, user_id: str) -> dict[str, Any]:
        alerts = self.get_alerts(user_id, limit=1000)
        return {
            "total": len(alerts),
            "critical": sum(1 for a in alerts if a["grade"] == "CRITICAL"),
            "high": sum(1 for a in alerts if a["grade"] == "HIGH"),
            "medium": sum(1 for a in alerts if a["grade"] == "MEDIUM"),
            "low": sum(1 for a in alerts if a["grade"] == "LOW"),
            "action_required": sum(1 for a in alerts if not a["acknowledged"] and a["grade"] in ("CRITICAL", "HIGH")),
        }


smart_alert_service = SmartAlertService()
