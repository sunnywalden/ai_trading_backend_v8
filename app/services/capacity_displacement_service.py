"""
容量置换服务（Capacity Displacement Service）

当新信号被 Layer 2 以 MAX_POSITIONS_REACHED 拒绝时，
与当前最弱持仓进行质量对比：

  - 若新信号质量（conviction_score）高于最弱持仓评分 + MIN_SCORE_DELTA，
    则自动创建对最弱持仓的 EXIT 信号（"腾仓"），
    并将入场信号置回 VALIDATED 等待下一轮决策循环。
  - 否则维持原有拒绝行为。

阈值说明
--------
MIN_INBOUND_QUALITY : 入场信号最低 conviction_score，低于此值不触发置换
MIN_SCORE_DELTA     : 新信号需超出最弱持仓评分的最小差值
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import (
    SignalSource,
    SignalStatus,
    SignalType,
    TradingSignal,
)

logger = logging.getLogger(__name__)

# ── 置换阈值 ─────────────────────────────────────────────────────────────────
MIN_INBOUND_QUALITY: float = 55.0   # 入场信号 conviction_score 最低要求
MIN_SCORE_DELTA: int = 5            # 新信号需比最弱持仓高出的评分差值


@dataclass
class DisplacementResult:
    """置换评估结果"""
    displaced: bool                          # 是否触发了置换
    incoming_symbol: str                     # 入场信号标的
    incoming_quality: float                  # 入场信号质量分
    target_symbol: Optional[str] = None      # 被替换的持仓标的
    target_score: Optional[int] = None       # 被替换持仓的评分
    target_recommendation: Optional[str] = None
    exit_signal_db_id: Optional[int] = None  # 创建的 EXIT 信号 DB id
    reason: str = ""                         # 未触发时的原因说明


class CapacityDisplacementService:
    """容量置换服务 — 在持仓满仓时评估是否可进行质量置换"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 主入口 ─────────────────────────────────────────────────────────────
    async def evaluate_and_displace(
        self,
        account_id: str,
        signal_id: int,
        signal_symbol: str,
        signal_quality_score: float,
        current_positions: Dict[str, Any],
    ) -> DisplacementResult:
        """
        评估是否触发容量置换。

        Parameters
        ----------
        account_id          : 账户 ID
        signal_id           : 被拦截信号的 DB id
        signal_symbol       : 被拦截信号的标的
        signal_quality_score: 被拦截信号的 conviction_score（0-100）
        current_positions   : {symbol: {qty, avg_cost, current_price, ...}} 
                              来自 PositionMonitor.get_positions_snapshot()
        """
        symbol_upper = str(signal_symbol).upper()

        # 1. 最低质量门槛
        if signal_quality_score < MIN_INBOUND_QUALITY:
            return DisplacementResult(
                displaced=False,
                incoming_symbol=symbol_upper,
                incoming_quality=signal_quality_score,
                reason=(
                    f"incoming quality {signal_quality_score:.1f} < "
                    f"MIN_INBOUND_QUALITY {MIN_INBOUND_QUALITY}"
                ),
            )

        if not current_positions:
            return DisplacementResult(
                displaced=False,
                incoming_symbol=symbol_upper,
                incoming_quality=signal_quality_score,
                reason="no current positions to displace",
            )

        # 2. 获取已有待执行 EXIT 的标的（避免重复触发）
        pending_exits = await self._get_pending_exit_symbols(account_id)

        # 3. 对每个持仓评分
        candidates = await self._score_positions(
            account_id=account_id,
            positions=current_positions,
            exclude_symbols=pending_exits | {symbol_upper},
        )

        if not candidates:
            return DisplacementResult(
                displaced=False,
                incoming_symbol=symbol_upper,
                incoming_quality=signal_quality_score,
                reason="no eligible positions to compare (all pending-exit or same symbol)",
            )

        # 4. 找最弱持仓（overall_score 最低）
        candidates.sort(key=lambda c: c["overall_score"])
        weakest = candidates[0]
        weakest_symbol: str = weakest["symbol"]
        weakest_score: int = weakest["overall_score"]

        # 5. 比较
        if signal_quality_score <= weakest_score + MIN_SCORE_DELTA:
            return DisplacementResult(
                displaced=False,
                incoming_symbol=symbol_upper,
                incoming_quality=signal_quality_score,
                target_symbol=weakest_symbol,
                target_score=weakest_score,
                target_recommendation=weakest.get("recommendation"),
                reason=(
                    f"incoming {signal_quality_score:.1f} ≤ weakest "
                    f"{weakest_symbol}({weakest_score}) + delta({MIN_SCORE_DELTA})"
                ),
            )

        # 6. 触发置换：为最弱持仓创建 EXIT 信号
        qty = float(current_positions[weakest_symbol.lower()].get("qty") or 0)
        if qty == 0:
            # 尝试 upper-case key
            qty = float(current_positions.get(weakest_symbol, {}).get("qty") or 0)

        exit_signal = await self._create_displacement_exit_signal(
            account_id         = account_id,
            symbol             = weakest_symbol,
            qty                = qty,
            position_score     = weakest_score,
            recommendation     = weakest.get("recommendation", "SELL"),
            trigger_signal_id  = signal_id,
            trigger_symbol     = symbol_upper,
            trigger_quality    = signal_quality_score,
        )

        await self.db.flush()  # 写入但不 commit，由调用方控制事务
        exit_db_id: Optional[int] = exit_signal.id  # flush 后可读

        logger.info(
            "[CapacityDisplacement] 置换触发: EXIT %s(score=%d) ← 新信号 %s(quality=%.1f) "
            "触发信号ID=%d, EXIT信号ID=%s",
            weakest_symbol, weakest_score,
            symbol_upper, signal_quality_score,
            signal_id, exit_db_id,
        )

        return DisplacementResult(
            displaced=True,
            incoming_symbol=symbol_upper,
            incoming_quality=signal_quality_score,
            target_symbol=weakest_symbol,
            target_score=weakest_score,
            target_recommendation=weakest.get("recommendation"),
            exit_signal_db_id=exit_db_id,
            reason=(
                f"displaced {weakest_symbol}(score={weakest_score}) "
                f"for {symbol_upper}(quality={signal_quality_score:.1f})"
            ),
        )

    # ── 内部方法: 对当前持仓评分 ───────────────────────────────────────────
    async def _score_positions(
        self,
        account_id: str,
        positions: Dict[str, Any],
        exclude_symbols: set,
    ) -> List[Dict[str, Any]]:
        """调用 PositionScoringService 对每个持仓计算评分，返回候选列表。"""
        from app.services.position_scoring_service import PositionScoringService

        scorer = PositionScoringService()
        candidates: List[Dict[str, Any]] = []

        for raw_symbol, pos_data in positions.items():
            symbol = str(raw_symbol).upper()
            if symbol in exclude_symbols:
                continue

            last_price: Optional[float] = pos_data.get("current_price")
            try:
                score_obj = await scorer.calculate_position_score(
                    symbol=symbol,
                    current_price=last_price,
                    force_refresh=False,  # 使用缓存，避免大量 API 请求
                )
            except Exception as exc:
                logger.warning(
                    "[CapacityDisplacement] 评分失败 %s: %s，使用默认 50", symbol, exc
                )
                score_obj = None

            if score_obj is not None:
                overall_score = int(getattr(score_obj, "overall_score", 50) or 50)
                recommendation = str(getattr(score_obj, "recommendation", "HOLD") or "HOLD").upper()
            else:
                overall_score = 50
                recommendation = "HOLD"

            qty = float(pos_data.get("qty") or 0)
            candidates.append({
                "symbol": symbol,
                "overall_score": overall_score,
                "recommendation": recommendation,
                "qty": qty,
            })

        return candidates

    # ── 内部方法: 查询待执行 EXIT 标的 ────────────────────────────────────
    async def _get_pending_exit_symbols(self, account_id: str) -> set:
        """返回该账户已有 GENERATED/VALIDATED/QUEUED/EXECUTING EXIT 信号的标的集合。"""
        stmt = select(TradingSignal.symbol).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.signal_type == SignalType.EXIT,
                TradingSignal.status.in_([
                    SignalStatus.GENERATED,
                    SignalStatus.VALIDATED,
                    SignalStatus.QUEUED,
                    SignalStatus.EXECUTING,
                ]),
            )
        )
        result = await self.db.execute(stmt)
        return {str(row[0]).upper() for row in result.all() if row and row[0]}

    # ── 内部方法: 创建置换 EXIT 信号 ───────────────────────────────────────
    async def _create_displacement_exit_signal(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        position_score: int,
        recommendation: str,
        trigger_signal_id: int,
        trigger_symbol: str,
        trigger_quality: float,
    ) -> TradingSignal:
        """构造并写入 EXIT TradingSignal（status=GENERATED），由调用方负责 commit。"""
        direction = "LONG"  # 平多头仓位

        notes = (
            f"容量置换：AI 评分 {position_score}/100 (建议: {recommendation}) — "
            f"为入场信号 {trigger_symbol}(quality={trigger_quality:.1f}) 腾仓，"
            f"由 CapacityDisplacementService 自动生成"
        )

        metadata: Dict[str, Any] = {
            "capacity_displacement": True,
            "displacement_trigger_signal_id": trigger_signal_id,
            "displacement_trigger_symbol": trigger_symbol,
            "displacement_trigger_quality": trigger_quality,
            "displaced_position_score": position_score,
            "displaced_recommendation": recommendation,
            "closing_intent": "EXIT",
            "execution_path": "FAST_CLOSE",
            "generated_by": "CapacityDisplacementService",
        }

        signal = TradingSignal(
            signal_id          = str(uuid4()),
            account_id         = account_id,
            user_id            = account_id,
            symbol             = symbol,
            signal_type        = SignalType.EXIT,
            signal_source      = SignalSource.RISK_MGMT,
            status             = SignalStatus.GENERATED,
            direction          = direction,
            quantity_mode      = "ABS_SHARES",
            quantity_value     = abs(qty) if qty else 0.0,
            suggested_quantity = abs(qty) if qty else 0.0,
            signal_strength    = max(0.1, (100 - position_score) / 100),
            confidence         = max(0.1, (100 - position_score) / 100),
            risk_score         = (100 - position_score) / 100,
            priority           = 91,  # 高于 REDUCE(65)，低于容量守卫(92)
            notes              = notes,
            max_holding_days   = None,
            created_at         = datetime.utcnow(),
            extra_metadata     = metadata,
        )
        self.db.add(signal)
        return signal
