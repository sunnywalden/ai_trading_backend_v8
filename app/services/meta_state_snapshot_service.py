"""V11.0.1 M2 — MetaStateSnapshotService

系统元状态聚合服务：每个决策周期生成一份结构化的「系统自知画像」，
整合当前所有维度的阻塞信号、闲置资本状态与可观察异常，
为前端 Autonomy 页面和 M3 改进引擎提供原料。

核心输出：
  - throttled_signals  : 被置信度阈值摩擦阻断的开仓信号列表
  - false_hold_alerts  : 被持续压制的 REDUCE/EXIT 告警列表
  - capital_state      : 当前资本利用率快照
  - model_state        : 摩擦全局统计（活跃摩擦 ticker 数等）

数据流：
  - throttled_signals 来自 ConvictionFrictionTracker (Redis SCAN)
  - false_hold_alerts 来自 position_rebalance_monitor emit_false_hold_alert (Redis keys)
  - capital_state     来自 GrossExposureAllocator.build_runtime_summary()

持久化：写入 Redis（TTL 1h）供快速读取，后台任务可选写入 MetaStateSnapshot 表（M2完整版）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SNAPSHOT_REDIS_KEY = "meta_state:latest"
_SNAPSHOT_TTL = 3600  # 1 hour
_SNAPSHOT_DB_RETENTION_DAYS = 90


@dataclass
class MetaStateSnapshot:
    """系统元状态快照。"""

    account_id: str = ""
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    throttled_signals: list[dict] = field(default_factory=list)
    false_hold_alerts: list[dict] = field(default_factory=list)
    capital_state: dict = field(default_factory=dict)
    model_state: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "throttled_signals": self.throttled_signals,
            "false_hold_alerts": self.false_hold_alerts,
            "capital_state": self.capital_state,
            "model_state": self.model_state,
        }


class MetaStateSnapshotService:
    """
    元状态快照服务。

    使用示例::

        snapshot = await meta_state_service.build_snapshot(
            account_id="ACC001",
            positions=positions_dict,
            equity=905000.0,
            regime="BULL_TREND",
        )
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    async def build_snapshot(
        self,
        *,
        account_id: str,
        positions: dict[str, Any],
        equity: float,
        regime: Optional[str] = None,
        db: AsyncSession | None = None,
    ) -> MetaStateSnapshot:
        """
        构建当前系统元状态快照并写入 Redis。

        Args:
            account_id: 账户 ID
            positions:  当前持仓字典（symbol → position_dict）
            equity:     当前账户净值
            regime:     当前市场体制（可选，用于 CVS 上下文）
        """
        throttled = await self._gather_throttled_signals()
        false_holds = await self._gather_false_hold_alerts(account_id)
        capital = self._compute_capital_state(positions, equity)
        model = self._compute_model_state(throttled, false_holds)

        snap = MetaStateSnapshot(
            account_id=account_id,
            throttled_signals=throttled,
            false_hold_alerts=false_holds,
            capital_state=capital,
            model_state=model,
        )
        await self._persist_snapshot(snap, db=db)
        logger.info(
            "[MetaState] snapshot built id=%s throttled=%d false_holds=%d",
            snap.snapshot_id,
            len(throttled),
            len(false_holds),
        )
        return snap

    async def get_latest_snapshot(
        self,
        *,
        db: AsyncSession | None = None,
        account_id: str | None = None,
    ) -> Optional[MetaStateSnapshot]:
        """优先从 Redis 获取最新快照；若 miss 则回退到 DB。"""
        try:
            if self._redis is not None:
                raw = await self._redis.get(_SNAPSHOT_REDIS_KEY)
                if raw is not None:
                    data = json.loads(raw)
                    return self._snapshot_from_payload(data)
        except Exception as exc:
            logger.warning("[MetaState] get_latest_snapshot failed: %s", exc)

        if db is None or not account_id:
            return None

        try:
            from app.models.meta_state_snapshot import \
                MetaStateSnapshot as MetaStateSnapshotRecord

            stmt = (
                select(MetaStateSnapshotRecord)
                .where(MetaStateSnapshotRecord.account_id == account_id)
                .order_by(MetaStateSnapshotRecord.generated_at.desc())
                .limit(1)
            )
            row = (await db.execute(stmt)).scalars().first()
            if row is None:
                return None
            payload = row.snapshot_json or {}
            if not isinstance(payload, dict):
                payload = {}
            if "account_id" not in payload:
                payload["account_id"] = account_id
            if "snapshot_id" not in payload:
                payload["snapshot_id"] = row.snapshot_id
            if "generated_at" not in payload and row.generated_at is not None:
                payload["generated_at"] = row.generated_at.isoformat()
            return self._snapshot_from_payload(payload)
        except Exception as exc:
            logger.warning("[MetaState] DB latest snapshot fallback failed: %s", exc)
            return None

    # ──────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────

    async def _gather_throttled_signals(self) -> list[dict]:
        """从 ConvictionFrictionTracker 收集所有摩擦信号。"""
        try:
            from app.services.conviction_friction_tracker import \
                conviction_friction_tracker

            states = await conviction_friction_tracker.get_all_throttled_signals(
                min_rejection_count=1
            )
            return [s.to_dict() for s in states]
        except Exception as exc:
            logger.warning("[MetaState] _gather_throttled_signals: %s", exc)
            return []

    async def _gather_false_hold_alerts(self, account_id: str) -> list[dict]:
        """从 Redis 收集 PositionRebalanceMonitor 发出的 False-Hold 告警。"""
        if self._redis is None:
            return []
        results: list[dict] = []
        try:
            pattern = f"false_hold_alert:{account_id}:*"
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    raw = await self._redis.get(key)
                    if raw:
                        try:
                            results.append(json.loads(raw))
                        except Exception:
                            pass
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("[MetaState] _gather_false_hold_alerts: %s", exc)
        return results

    @staticmethod
    def _compute_capital_state(
        positions: dict[str, Any], equity: float
    ) -> dict[str, Any]:
        """计算当前资本利用率快照。"""
        if equity <= 0:
            return {"equity": 0.0, "idle_cash_ratio": 1.0}
        try:
            gross_notional = sum(
                abs(float(p.get("qty", 0) or 0))
                * abs(float(p.get("current_price", 0) or p.get("last_price", 0) or 0))
                for p in positions.values()
                if isinstance(p, dict)
            )
            gross_pct = gross_notional / equity
            idle_ratio = max(0.0, 1.0 - gross_pct)
            return {
                "equity": round(equity, 2),
                "positions_count": len(positions),
                "gross_notional": round(gross_notional, 2),
                "gross_exposure_pct": round(gross_pct, 4),
                "idle_cash_ratio": round(idle_ratio, 4),
            }
        except Exception as exc:
            logger.warning("[MetaState] _compute_capital_state: %s", exc)
            return {"equity": equity, "error": str(exc)}

    @staticmethod
    def _compute_model_state(
        throttled: list[dict], false_holds: list[dict]
    ) -> dict[str, Any]:
        """计算模型状态摘要。"""
        eligible_count = sum(
            1 for t in throttled if t.get("soft_relief_eligible", False)
        )
        return {
            "active_friction_tickers": len(throttled),
            "soft_relief_eligible_count": eligible_count,
            "false_hold_count": len(false_holds),
            "total_blocked_signals": len(throttled) + len(false_holds),
        }

    @staticmethod
    def _snapshot_from_payload(data: dict[str, Any]) -> MetaStateSnapshot:
        return MetaStateSnapshot(
            account_id=str(data.get("account_id", "") or ""),
            snapshot_id=data.get("snapshot_id", ""),
            generated_at=data.get("generated_at", ""),
            throttled_signals=data.get("throttled_signals", []),
            false_hold_alerts=data.get("false_hold_alerts", []),
            capital_state=data.get("capital_state", {}),
            model_state=data.get("model_state", {}),
        )

    async def _persist_snapshot(
        self,
        snap: MetaStateSnapshot,
        *,
        db: AsyncSession | None = None,
    ) -> None:
        """写入 Redis（TTL 1h）并可选持久化到 DB（保留 90 天）。"""
        try:
            if self._redis is not None:
                await self._redis.set(
                    _SNAPSHOT_REDIS_KEY,
                    json.dumps(snap.to_dict()),
                    ex=_SNAPSHOT_TTL,
                )
        except Exception as exc:
            logger.warning("[MetaState] _persist_snapshot failed: %s", exc)

        if db is None:
            return

        try:
            from app.models.meta_state_snapshot import \
                MetaStateSnapshot as MetaStateSnapshotRecord

            record = MetaStateSnapshotRecord(
                snapshot_id=snap.snapshot_id,
                account_id=snap.account_id,
                throttled_signals_count=len(snap.throttled_signals),
                false_hold_count=len(snap.false_hold_alerts),
                total_blocked_signals=int(
                    (snap.model_state or {}).get("total_blocked_signals", 0) or 0
                ),
                idle_cash_ratio=(snap.capital_state or {}).get("idle_cash_ratio"),
                gross_exposure_pct=(snap.capital_state or {}).get(
                    "gross_exposure_pct"
                ),
                snapshot_json=snap.to_dict(),
                notes="V11.0.1 meta-state snapshot",
            )
            db.add(record)

            cutoff = datetime.now() - timedelta(
                days=_SNAPSHOT_DB_RETENTION_DAYS
            )
            await db.execute(
                delete(MetaStateSnapshotRecord).where(
                    MetaStateSnapshotRecord.generated_at < cutoff
                )
            )
            await db.commit()
        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning("[MetaState] DB persist failed: %s", exc)


# 单例（在 app startup 注入 Redis）
meta_state_service = MetaStateSnapshotService(redis_client=None)


def init_meta_state_service(redis_client) -> None:
    """在 app 启动时注入 Redis 客户端。"""
    meta_state_service._redis = redis_client  # noqa: SLF001
    logger.info("[MetaState] Redis client injected")
