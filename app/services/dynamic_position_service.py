"""V10.2-M3: 动态仓位生命周期引擎

包含：
- PositionStateMachine: 仓位状态流转（ENTERING→…→CLOSED）
- ScaleInEngine: 加仓决策（3 条规则：置信度提升/阻力突破/策略共振）
- ScaleOutEngine: 减仓/平仓决策（6 条规则）
- TrailingStopEngine: 追踪止损（按市场状态动态调整止损比例）

典型调用::

    engine = DynamicPositionService()
    decision = await engine.evaluate_position(db, position_id=123, current_price=155.0, fused_confidence=0.78)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import event_bus, Topics

logger = logging.getLogger(__name__)


# ── 仓位状态机枚举 ────────────────────────────────────────────────────────────

class PositionState(str, Enum):
    ENTERING      = "ENTERING"       # 初始开仓中
    HELD          = "HELD"           # 正常持有
    SCALING_IN    = "SCALING_IN"     # 正在加仓
    SCALING_OUT   = "SCALING_OUT"    # 正在减仓
    EXITING_FULL  = "EXITING_FULL"   # 全部平仓中
    STOP_LOSS_EXIT = "STOP_LOSS_EXIT" # 止损平仓
    CLOSED        = "CLOSED"         # 已平仓


class ScaleDecision(str, Enum):
    HOLD          = "HOLD"
    SCALE_IN_25   = "SCALE_IN_25"    # 加仓 25%（信心提升）
    SCALE_IN_20   = "SCALE_IN_20"    # 加仓 20%（突破阻力）
    SCALE_IN_15   = "SCALE_IN_15"    # 加仓 15%（多策略共振）
    SCALE_OUT_33  = "SCALE_OUT_33"   # 减仓 33%（部分止盈）
    SCALE_OUT_50  = "SCALE_OUT_50"   # 减仓 50%（信号衰减）
    SCALE_OUT_75  = "SCALE_OUT_75"   # 减仓 75%（论文破裂）
    EXIT_FULL     = "EXIT_FULL"      # 全部平仓（时间止损/止盈）
    STOP_LOSS     = "STOP_LOSS"      # 止损平仓（紧急）


@dataclass
class PositionContext:
    """评估仓位决策所需的上下文（由调用方填充）"""
    position_id:        int
    symbol:             str
    regime:             str                  # 当前市场状态（RegimeType 值）
    entry_price:        float
    current_price:      float
    quantity:           float
    max_allowed_quantity: float             # 策略允许的最大仓位
    fused_confidence:   float               # 六维融合信号置信度 0-1
    prev_confidence:    float               # 上一次置信度
    hold_days:          int
    unrealized_pnl_pct: float               # 浮动盈亏百分比
    trailing_high:      Optional[float]     # 追踪止损的历史最高价
    scale_in_count:     int                 # 已加仓次数
    strategy_count:     int                 # 同向策略数量
    resistance_broken:  bool                # 是否突破技术阻力
    thesis_intact:      bool                # 投资逻辑是否还成立
    max_hold_days:      int = 60            # 时间止损上限
    stop_loss_pct:      float = -0.08       # 止损线（负值）


@dataclass
class PositionDecisionResult:
    """决策结果"""
    decision:         ScaleDecision
    new_state:        PositionState
    quantity_delta:   float           # 正=加仓量，负=减仓量，0=不操作
    reason:           str
    trailing_high_update: Optional[float] = None  # 若追踪止损有更新
    metadata:         dict = field(default_factory=dict)


# ── 追踪止损参数（按市场状态）────────────────────────────────────────────────

_TRAIL_PCT_BY_REGIME: dict[str, float] = {
    "BULL_TREND": 0.05,
    "BEAR_TREND": 0.03,
    "SIDEWAYS":   0.04,
    "HIGH_VOL":   0.03,
    "CRISIS":     0.02,
}
_TRAILING_ACTIVATE_PCT = 0.01  # 盈利超过 1% 后激活追踪止损


class TrailingStopEngine:
    """按市值最高点动态追踪的止损引擎"""

    def check(
        self,
        ctx: PositionContext,
    ) -> Optional[PositionDecisionResult]:
        """若触发追踪止损，返回 STOP_LOSS 决策；否则返回 None（附带 trailing_high 更新）。"""
        if ctx.unrealized_pnl_pct < _TRAILING_ACTIVATE_PCT:
            return None  # 未达到激活门槛

        trail_pct = _TRAIL_PCT_BY_REGIME.get(ctx.regime, 0.03)
        new_high  = max(ctx.trailing_high or ctx.entry_price, ctx.current_price)

        # 检查是否从最高点回撤超过 trail_pct
        drawdown = (ctx.current_price - new_high) / new_high
        if drawdown < -trail_pct:
            return PositionDecisionResult(
                decision=ScaleDecision.STOP_LOSS,
                new_state=PositionState.STOP_LOSS_EXIT,
                quantity_delta=-ctx.quantity,
                reason=f"trailing stop hit: {drawdown:.2%} drawdown from high {new_high:.2f} (trail={trail_pct:.0%})",
                trailing_high_update=new_high,
            )

        # 更新追踪高价
        result = PositionDecisionResult(
            decision=ScaleDecision.HOLD,
            new_state=PositionState.HELD,
            quantity_delta=0.0,
            reason="trailing stop active, no trigger",
            trailing_high_update=new_high,
        )
        return result if new_high > (ctx.trailing_high or 0) else None


class ScaleInEngine:
    """加仓决策引擎（最多加仓 3 次）"""

    MAX_SCALE_IN = 3

    def evaluate(self, ctx: PositionContext) -> Optional[PositionDecisionResult]:
        if ctx.scale_in_count >= self.MAX_SCALE_IN:
            return None
        if ctx.quantity >= ctx.max_allowed_quantity:
            return None

        # 规则 1: 置信度提升 10pp → 加仓 25%
        confidence_delta = ctx.fused_confidence - ctx.prev_confidence
        if confidence_delta >= 0.10 and ctx.fused_confidence >= 0.70:
            add_qty = min(ctx.quantity * 0.25, ctx.max_allowed_quantity - ctx.quantity)
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_IN_25,
                new_state=PositionState.SCALING_IN,
                quantity_delta=add_qty,
                reason=f"confidence boost +{confidence_delta:.1%}: {ctx.prev_confidence:.0%}→{ctx.fused_confidence:.0%}",
            )

        # 规则 2: 突破技术阻力 → 加仓 20%
        if ctx.resistance_broken and ctx.fused_confidence >= 0.65:
            add_qty = min(ctx.quantity * 0.20, ctx.max_allowed_quantity - ctx.quantity)
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_IN_20,
                new_state=PositionState.SCALING_IN,
                quantity_delta=add_qty,
                reason="resistance breakout confirmed",
            )

        # 规则 3: 多策略共振（2+ 策略同向）→ 加仓 15%
        if ctx.strategy_count >= 2 and ctx.fused_confidence >= 0.65:
            add_qty = min(ctx.quantity * 0.15, ctx.max_allowed_quantity - ctx.quantity)
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_IN_15,
                new_state=PositionState.SCALING_IN,
                quantity_delta=add_qty,
                reason=f"strategy resonance: {ctx.strategy_count} strategies aligned",
            )

        return None


class ScaleOutEngine:
    """减仓 / 平仓决策引擎（6 条规则，按优先级排序）"""

    def evaluate(self, ctx: PositionContext) -> Optional[PositionDecisionResult]:
        # 规则 1 (最高优先): 止损
        if ctx.unrealized_pnl_pct <= ctx.stop_loss_pct:
            return PositionDecisionResult(
                decision=ScaleDecision.STOP_LOSS,
                new_state=PositionState.STOP_LOSS_EXIT,
                quantity_delta=-ctx.quantity,
                reason=f"stop loss triggered: pnl={ctx.unrealized_pnl_pct:.2%} <= {ctx.stop_loss_pct:.2%}",
            )

        # 规则 2: 信号衰减（置信度跌破 0.45 且仍有盈利）
        if ctx.fused_confidence < 0.45 and ctx.unrealized_pnl_pct > 0:
            reduce_qty = ctx.quantity * 0.50
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_OUT_50,
                new_state=PositionState.SCALING_OUT,
                quantity_delta=-reduce_qty,
                reason=f"signal decay: confidence={ctx.fused_confidence:.0%}",
            )

        # 规则 3: 论文破裂（基本面逻辑不再成立）
        if not ctx.thesis_intact:
            reduce_qty = ctx.quantity * 0.75
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_OUT_75,
                new_state=PositionState.SCALING_OUT,
                quantity_delta=-reduce_qty,
                reason="investment thesis broken",
            )

        # 规则 4: 时间止损（持有超过 max_hold_days）
        if ctx.hold_days >= ctx.max_hold_days:
            return PositionDecisionResult(
                decision=ScaleDecision.EXIT_FULL,
                new_state=PositionState.EXITING_FULL,
                quantity_delta=-ctx.quantity,
                reason=f"time stop: hold_days={ctx.hold_days} >= {ctx.max_hold_days}",
            )

        # 规则 5: 部分目标达到（盈利 10-20%，减 33%）
        if 0.10 <= ctx.unrealized_pnl_pct < 0.20:
            reduce_qty = ctx.quantity * 0.33
            return PositionDecisionResult(
                decision=ScaleDecision.SCALE_OUT_33,
                new_state=PositionState.SCALING_OUT,
                quantity_delta=-reduce_qty,
                reason=f"partial target: pnl={ctx.unrealized_pnl_pct:.2%}",
            )

        # 规则 6: 完全目标（盈利 20%+，全部平仓）
        if ctx.unrealized_pnl_pct >= 0.20:
            return PositionDecisionResult(
                decision=ScaleDecision.EXIT_FULL,
                new_state=PositionState.EXITING_FULL,
                quantity_delta=-ctx.quantity,
                reason=f"full target hit: pnl={ctx.unrealized_pnl_pct:.2%}",
            )

        return None


class DynamicPositionService:
    """
    动态仓位生命周期服务门面。

    evaluate_position() → 综合调用 TrailingStop / ScaleOut / ScaleIn 三个引擎，
    返回最终决策，并发布对应事件总线消息。
    """

    def __init__(self) -> None:
        self._trailing = TrailingStopEngine()
        self._scale_in = ScaleInEngine()
        self._scale_out = ScaleOutEngine()

    async def evaluate_position(
        self,
        ctx: PositionContext,
        db: Optional[AsyncSession] = None,
    ) -> PositionDecisionResult:
        """综合评估仓位，返回推荐决策。

        优先级：TrailingStop > ScaleOut > ScaleIn > Hold
        """
        # 1. 追踪止损优先
        ts_result = self._trailing.check(ctx)
        if ts_result and ts_result.decision != ScaleDecision.HOLD:
            await self._publish(ctx, ts_result)
            return ts_result

        # 2. 减仓 / 止损
        so_result = self._scale_out.evaluate(ctx)
        if so_result:
            await self._publish(ctx, so_result)
            return so_result

        # 3. 加仓
        si_result = self._scale_in.evaluate(ctx)
        if si_result:
            await self._publish(ctx, si_result)
            return si_result

        # 4. 持有不动
        hold = PositionDecisionResult(
            decision=ScaleDecision.HOLD,
            new_state=PositionState.HELD,
            quantity_delta=0.0,
            reason="all conditions nominal—hold position",
            trailing_high_update=ts_result.trailing_high_update if ts_result else None,
        )
        return hold

    async def _publish(self, ctx: PositionContext, result: PositionDecisionResult) -> None:
        """根据决策类别发布对应的事件总线消息。"""
        try:
            if result.decision in (ScaleDecision.STOP_LOSS, ScaleDecision.EXIT_FULL,
                                   ScaleDecision.SCALE_OUT_33, ScaleDecision.SCALE_OUT_50,
                                   ScaleDecision.SCALE_OUT_75):
                await event_bus.publish(
                    Topics.CLOSE_SIGNAL_TRIGGERED,
                    {
                        "position_id": ctx.position_id,
                        "symbol":      ctx.symbol,
                        "reason":      result.reason,
                        "pct":         abs(result.quantity_delta / ctx.quantity) if ctx.quantity else 1.0,
                        "decision":    result.decision,
                    },
                )
            elif result.decision.startswith("SCALE_IN"):
                await event_bus.publish(
                    Topics.SIGNAL_CONFIDENCE_UPDATED,
                    {
                        "position_id": ctx.position_id,
                        "symbol":      ctx.symbol,
                        "old_confidence": ctx.prev_confidence,
                        "new_confidence": ctx.fused_confidence,
                        "scale_decision": result.decision,
                    },
                )
        except Exception as e:
            logger.warning(f"[DynamicPosition] event publish failed: {e}")

    async def get_scale_in_candidates(
        self,
        positions: list[PositionContext],
    ) -> list[dict]:
        """批量扫描所有持仓，返回符合加仓条件的候选。"""
        candidates = []
        for ctx in positions:
            si = self._scale_in.evaluate(ctx)
            if si:
                candidates.append({
                    "position_id":  ctx.position_id,
                    "symbol":       ctx.symbol,
                    "decision":     si.decision,
                    "quantity_delta": si.quantity_delta,
                    "reason":       si.reason,
                    "confidence":   ctx.fused_confidence,
                })
        return candidates


# ── 模块级单例 ────────────────────────────────────────────────────────────────
dynamic_position_service = DynamicPositionService()
