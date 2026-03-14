"""V11.0.1 M1.5.1 — ConvictionFrictionTracker

置信度摩擦追踪器：Redis 后端持久化每个 symbol/direction/regime 组合近命中
被拒的连续次数，判定是否进入"阈值摩擦状态"，为 Layer 4 阈值软化提供依据。

设计约束：
- 仅 CAPITAL_VELOCITY_V1101_ENABLED=True 时被调用，否则不影响现有流程
- 所有读写均使用 Redis Hash，TTL=24小时（仅追踪当日摩擦）
- 不依赖 DB，保持轻量，不阻塞主决策链路
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_KEY_PREFIX = "cv_friction"
_TTL_SECONDS = 86400  # 24 小时


@dataclass
class FrictionState:
    """单个 symbol/direction/regime 的摩擦状态快照。"""

    symbol: str
    direction: str
    regime: str
    rejection_count: int = 0
    last_conviction: float = 0.0
    threshold_at_rejection: int = 0
    last_rejected_at: Optional[str] = None
    soft_relief_used_count: int = 0
    soft_relief_last_used_at: Optional[str] = None
    # 下游计算字段（非存储）
    friction_gap: float = 0.0  # threshold - last_conviction
    composite_score: float = 0.0  # 最近一次信号的 composite_score
    resonance_bonus: float = 0.0  # 最近一次信号的 resonance_bonus
    soft_relief_eligible: bool = False  # 是否满足软化条件

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "regime": self.regime,
            "rejection_count": self.rejection_count,
            "last_conviction": round(self.last_conviction, 2),
            "threshold_at_rejection": self.threshold_at_rejection,
            "last_rejected_at": self.last_rejected_at,
            "soft_relief_used_count": self.soft_relief_used_count,
            "soft_relief_last_used_at": self.soft_relief_last_used_at,
            "friction_gap": round(self.friction_gap, 2),
            "composite_score": round(self.composite_score, 2),
            "resonance_bonus": round(self.resonance_bonus, 2),
            "soft_relief_eligible": self.soft_relief_eligible,
        }


class ConvictionFrictionTracker:
    """
    置信度摩擦追踪器。

    使用示例::

        tracker = ConvictionFrictionTracker(redis_client)
        await tracker.record_rejection(
            symbol="ORCL", direction="LONG", regime="BULL_TREND",
            conviction=92.0, threshold=93,
            composite_score=98.0, resonance_bonus=90.0,
        )
        state = await tracker.get_friction_state("ORCL", "LONG", "BULL_TREND")
        if state and state.rejection_count >= 3:
            # 触发软化检查
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    def set_redis_client(self, redis_client) -> None:
        self._redis = redis_client

    @staticmethod
    def _build_key(symbol: str, direction: str, regime: str) -> str:
        return (
            f"{_KEY_PREFIX}:{symbol.upper()}:{direction.upper()}:" f"{regime.upper()}"
        )

    async def record_rejection(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
        conviction: float,
        threshold: int,
        composite_score: float = 0.0,
        resonance_bonus: float = 0.0,
    ) -> int:
        """记录一次 Layer 4 拒绝，返回当前连续拒绝次数。"""
        if self._redis is None:
            return 0
        try:
            key = self._build_key(symbol, direction, regime)
            now_iso = datetime.now(timezone.utc).isoformat()
            pipe = self._redis.pipeline()
            pipe.hincrby(key, "rejection_count", 1)
            pipe.hset(key, "last_conviction", str(round(conviction, 4)))
            pipe.hset(key, "threshold_at_rejection", str(threshold))
            pipe.hset(key, "last_rejected_at", now_iso)
            pipe.hset(key, "composite_score", str(round(composite_score, 4)))
            pipe.hset(key, "resonance_bonus", str(round(resonance_bonus, 4)))
            pipe.expire(key, _TTL_SECONDS)
            results = await pipe.execute()
            current_count = int(results[0])
            logger.debug(
                "[FrictionTracker] rejection recorded %s %s %s "
                "conviction=%.1f threshold=%d count=%d",
                symbol,
                direction,
                regime,
                conviction,
                threshold,
                current_count,
            )
            return current_count
        except (RedisError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "[FrictionTracker] record_rejection failed: %s",
                exc,
            )
            return 0

    async def record_pass(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
    ) -> None:
        """信号通过 Layer 4 后重置摩擦状态。"""
        if self._redis is None:
            return
        try:
            key = self._build_key(symbol, direction, regime)
            await self._redis.delete(key)
            logger.debug(
                "[FrictionTracker] pass recorded, friction reset %s %s %s",
                symbol,
                direction,
                regime,
            )
        except (RedisError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("[FrictionTracker] record_pass failed: %s", exc)

    async def record_soft_relief_used(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
    ) -> None:
        """记录一次软化通过，更新 soft_relief_used_count。"""
        if self._redis is None:
            return
        try:
            key = self._build_key(symbol, direction, regime)
            now_iso = datetime.now(timezone.utc).isoformat()
            pipe = self._redis.pipeline()
            pipe.hincrby(key, "soft_relief_used_count", 1)
            pipe.hset(key, "soft_relief_last_used_at", now_iso)
            pipe.expire(key, _TTL_SECONDS)
            await pipe.execute()
        except (RedisError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "[FrictionTracker] record_soft_relief_used failed: %s",
                exc,
            )

    async def get_friction_state(
        self,
        symbol: str,
        direction: str,
        regime: str,
    ) -> Optional[FrictionState]:
        """获取指定 symbol/direction/regime 的摩擦状态；若无记录返回 None。"""
        if self._redis is None:
            return None
        try:
            key = self._build_key(symbol, direction, regime)
            data = await self._redis.hgetall(key)
            if not data:
                return None
            return FrictionState(
                symbol=symbol,
                direction=direction,
                regime=regime,
                rejection_count=int(data.get(b"rejection_count", 0)),
                last_conviction=float(data.get(b"last_conviction", 0.0)),
                threshold_at_rejection=int(data.get(b"threshold_at_rejection", 0)),
                last_rejected_at=(
                    data.get(b"last_rejected_at", b"").decode()
                    if data.get(b"last_rejected_at")
                    else None
                ),
                soft_relief_used_count=int(data.get(b"soft_relief_used_count", 0)),
                soft_relief_last_used_at=(
                    data.get(b"soft_relief_last_used_at", b"").decode()
                    if data.get(b"soft_relief_last_used_at")
                    else None
                ),
                composite_score=float(data.get(b"composite_score", 0.0)),
                resonance_bonus=float(data.get(b"resonance_bonus", 0.0)),
            )
        except (RedisError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "[FrictionTracker] get_friction_state failed: %s",
                exc,
            )
            return None

    async def can_use_soft_relief(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
        max_per_cycle: int = 1,
    ) -> bool:
        """检查本周期是否还有软化配额。"""
        state = await self.get_friction_state(symbol, direction, regime)
        if state is None:
            return True
        return state.soft_relief_used_count < max_per_cycle

    async def get_all_throttled_signals(
        self,
        *,
        min_rejection_count: int = 1,
    ) -> list[FrictionState]:
        """
        扫描 Redis 中所有当前处于摩擦状态的信号。
        注意：使用 SCAN 命令，不阻塞服务。
        """
        if self._redis is None:
            return []
        try:
            keys = await self._collect_keys()
            return await self._load_states(keys, min_rejection_count)
        except (RedisError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "[FrictionTracker] get_all_throttled_signals failed: %s", exc
            )
        return []

    async def _collect_keys(self) -> list[str]:
        """通过 SCAN 收集所有 cv_friction 键名。"""
        if self._redis is None:
            return []
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await self._redis.scan(
                cursor, match=f"{_KEY_PREFIX}:*", count=100
            )
            for raw_key in batch:
                keys.append(raw_key.decode() if isinstance(raw_key, bytes) else raw_key)
            if cursor == 0:
                break
        return keys

    async def _load_states(
        self,
        keys: list[str],
        min_rejection_count: int,
    ) -> list[FrictionState]:
        """根据键列表加载且过滤摩擦状态。"""
        results: list[FrictionState] = []
        for raw_key in keys:
            parts = raw_key.split(":")
            if len(parts) < 4:
                continue
            _, symbol, direction, regime = (
                parts[0],
                parts[1],
                parts[2],
                parts[3],
            )
            state = await self.get_friction_state(symbol, direction, regime)
            if state and state.rejection_count >= min_rejection_count:
                results.append(state)
        return results


# 单例（在 app startup 时通过 init_conviction_friction_tracker() 注入 Redis）
conviction_friction_tracker = ConvictionFrictionTracker(redis_client=None)


def init_conviction_friction_tracker(redis_client) -> None:
    """在 app 启动时注入 Redis 客户端。"""
    conviction_friction_tracker.set_redis_client(redis_client)
    logger.info("[FrictionTracker] Redis client injected")
