"""V10.2-M1: AsyncIO 异步发布/订阅事件总线

设计约定：
- 订阅者注册为 async callable；处理抛出的异常会被吞掉并记录日志，不影响其他订阅者。
- 同一 Topic 可注册多个订阅者，广播顺序不保证。
- 模块启动后在 lifespan 中调用各 XXX_allocator.register_handlers() 注册订阅者。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class Topics(str, Enum):
    """V10.2 事件主题枚举，与订阅者解耦"""

    # ── M1: 市场状态 ──────────────────────────────────────────────────────────
    REGIME_CHANGED = "regime.changed"  # 市场体制切换   payload: {"prev": str, "curr": str, "confidence": float}
    # ── 基础信号 / 风险 ───────────────────────────────────────────────────────
    SIGNAL_GENERATED = "signal.generated"  # 新信号产出     payload: TradingSignal dict
    RISK_BREACH = (
        "risk.breach"  # 风险门禁触发   payload: {"reason": str, "symbol": str}
    )
    ORDER_FILLED = "order.filled"  # 订单成交       payload: OrderFilled dict
    CIRCUIT_BREAKER = "circuit.breaker"  # 熔断触发       payload: {"account_id": str, "daily_loss": float}
    # ── M2: 事件驱动围栏 ──────────────────────────────────────────────────────
    EVENT_CALENDAR_ALERT = "event.calendar.alert"  # 事件提醒           payload: EventCalendarEntry.to_dict()
    EARNINGS_RESULT = "event.earnings.result"  # 财报结果录入        payload: {"symbol": str, "eps_actual": float, ...}
    # ── M3: 动态仓位生命周期 ──────────────────────────────────────────────────
    SIGNAL_CONFIDENCE_UPDATED = "signal.confidence.updated"  # 信号置信度变化  payload: {"symbol": str, "old": float, "new": float}
    POSITION_PNL_UPDATED = "position.pnl.updated"  # 仓位盈亏更新    payload: {"position_id": int, "pnl_pct": float}
    CLOSE_SIGNAL_TRIGGERED = "position.close.triggered"  # 平仓信号        payload: {"position_id": int, "reason": str, "pct": float}
    # ── M4: 六维信号融合 ──────────────────────────────────────────────────────
    FUSED_SIGNAL_READY = "signal.fused.ready"  # 融合信号就绪    payload: {"symbol": str, "fused_confidence": float}
    # ── M6: AI 洞察 ──────────────────────────────────────────────────────────
    INSIGHT_GENERATED = (
        "insight.generated"  # 新洞察生成     payload: AIInsight.to_dict()
    )
    AB_EXPERIMENT_DONE = (
        "ab.experiment.done"  # A/B 实验完成   payload: ABExperiment.to_dict()
    )
    # ── V10.4.4: Position-centric 生命周期事件 ───────────────────────────────
    POSITION_OPENED = "position.opened"  # 仓位首次成交确认  payload: {"position_id": int, "symbol": str, "account_id": str, "qty": float, "avg_price": float}
    POSITION_ADDED = "position.added"  # 加仓成交完成      payload: {"position_id": int, "symbol": str, "added_qty": float, "new_total_qty": float}
    POSITION_REDUCED = "position.reduced"  # 减仓成交完成      payload: {"position_id": int, "symbol": str, "reduced_qty": float, "remaining_qty": float, "closing_reason": str}
    POSITION_CLOSED = "position.closed"  # 仓位全部平仓      payload: {"position_id": int, "symbol": str, "closing_reason": str, "realized_pnl": float}
    POSITION_LIQUIDATED = "position.liquidated"  # 强制清算          payload: {"position_id": int, "symbol": str, "reason": str}
    POSITION_EXCEPTION = "position.exception"  # 仓位进入异常态    payload: {"position_id": int, "symbol": str, "exception_detail": str}
    # ── V10.4.4: ExecutionSlice 事件 ─────────────────────────────────────────
    SLICE_CREATED = "slice.created"  # 切片已创建        payload: {"slice_id": int, "position_id": int, "action": str, "qty": float}
    SLICE_FILLED = "slice.filled"  # 切片全部成交      payload: {"slice_id": int, "position_id": int, "filled_qty": float, "avg_price": float}
    SLICE_STUCK = "slice.stuck"  # 切片超时卡住      payload: {"slice_id": int, "position_id": int, "symbol": str, "elapsed_seconds": float}
    SLICE_FAILED = "slice.failed"  # 切片执行失败      payload: {"slice_id": int, "position_id": int, "error": str}


# Handler type alias
AsyncHandler = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """
    简单的进程内 AsyncIO 发布/订阅事件总线。

    使用示例::

        from app.core.event_bus import event_bus, Topics

        # 订阅
        async def on_regime_changed(payload: dict) -> None:
            ...
        event_bus.subscribe(Topics.REGIME_CHANGED, on_regime_changed)

        # 发布
        await event_bus.publish(Topics.REGIME_CHANGED, {"prev": "BULL", "curr": "CRISIS", "confidence": 0.91})
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[AsyncHandler]] = defaultdict(list)

    # ─────────────────────────────────────────
    # 订阅 / 取消订阅
    # ─────────────────────────────────────────

    def subscribe(self, topic: Topics | str, handler: AsyncHandler) -> None:
        """注册一个异步事件处理器到指定 topic。"""
        key = topic.value if isinstance(topic, Topics) else topic
        self._subscribers[key].append(handler)
        logger.debug(f"[EventBus] Subscribed {handler.__name__} to '{key}'")

    def unsubscribe(self, topic: Topics | str, handler: AsyncHandler) -> None:
        """从指定 topic 移除处理器（若不存在则静默忽略）。"""
        key = topic.value if isinstance(topic, Topics) else topic
        try:
            self._subscribers[key].remove(handler)
        except ValueError:
            pass

    # ─────────────────────────────────────────
    # 发布
    # ─────────────────────────────────────────

    async def publish(self, topic: Topics | str, payload: Any = None) -> int:
        """
        广播事件到所有订阅者。

        Parameters
        ----------
        topic   : 事件主题
        payload : 任意可序列化的 payload（建议 dict）

        Returns
        -------
        int : 成功调用的订阅者数量
        """
        key = topic.value if isinstance(topic, Topics) else topic
        handlers = list(self._subscribers.get(key, []))

        if not handlers:
            logger.debug(f"[EventBus] No subscribers for '{key}', skipping publish")
            return 0

        logger.info(
            f"[EventBus] Publishing '{key}' to {len(handlers)} subscriber(s). payload={payload!r}"[
                :200
            ]
        )

        success = 0
        for handler in handlers:
            try:
                await handler(payload)
                success += 1
            except Exception as exc:
                logger.exception(
                    f"[EventBus] Handler '{handler.__name__}' raised on topic '{key}': {exc}"
                )

        return success

    # ─────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────

    def subscriber_count(self, topic: Topics | str) -> int:
        key = topic.value if isinstance(topic, Topics) else topic
        return len(self._subscribers.get(key, []))

    def clear(self) -> None:
        """清空所有订阅（测试用）。"""
        self._subscribers.clear()

    def __repr__(self) -> str:  # pragma: no cover
        totals = {k: len(v) for k, v in self._subscribers.items() if v}
        return f"<EventBus subscribers={totals}>"


# 全局单例 —— 整个进程共享同一个 EventBus
event_bus: EventBus = EventBus()
