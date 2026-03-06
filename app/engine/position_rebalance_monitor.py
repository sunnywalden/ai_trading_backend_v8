"""
持仓再平衡监控器 — 将 AI 评分建议转化为可执行信号

职责：
  1. 读取当前账户持仓（来自 Broker）
  2. 查询每个持仓标的最新评分（PositionScore，24h 内有效）
  3. 将 REDUCE 建议 → SignalType.REDUCE（减仓 30-50%）
     将 SELL   建议 → SignalType.EXIT  （全部平仓）
  4. 写入 TradingSignal，状态 GENERATED，等待 AutonomousEngine 处理

与 PositionMonitor 的区别：
  - PositionMonitor：触发止损/止盈/超龄的「硬性」出场
  - PositionRebalanceMonitor：将 AI 评分给出的「软性」减仓/卖出建议转为信号

调用时机：
  - 由 quant_loop_jobs.run_position_rebalance_scan() 每小时触发
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.trading_signal import (
    TradingSignal, SignalType, SignalStatus, SignalSource,
)
from app.models.position_score import PositionScore

logger = logging.getLogger(__name__)

# 评分建议阈值
_SCORE_REDUCE_THRESHOLD = 54   # overall_score <= 54 → REDUCE
_SCORE_SELL_THRESHOLD   = 39   # overall_score <= 39 → EXIT/SELL

# 减仓默认比例（30% of current position）
_DEFAULT_REDUCE_RATIO   = 0.30

# 评分有效期（超过此时间的评分不参考）
_SCORE_VALID_HOURS = 24


class PositionRebalanceMonitor:
    """
    持仓再平衡监控器

    将 PositionScoringService 生成的 REDUCE/SELL 建议转化为
    TradingSignal，以便 AutonomousEngine 和 OrderExecutor 执行。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def scan(self, account_id: str) -> Dict[str, Any]:
        """
        主入口：扫描所有持仓的最新评分，按建议创建信号。

        Returns:
            {
                "scanned": int,
                "reduce_signals": int,
                "exit_signals": int,
                "skipped_no_score": int,
                "skipped_already_pending": int,
                "details": [...]
            }
        """
        positions = await self._fetch_positions(account_id)
        if not positions:
            return {
                "scanned": 0,
                "reduce_signals": 0,
                "exit_signals": 0,
                "skipped_no_score": 0,
                "skipped_already_pending": 0,
                "details": [],
            }

        reduce_count    = 0
        exit_count      = 0
        no_score_count  = 0
        already_pending = 0
        details: List[Dict[str, Any]] = []

        for pos in positions:
            symbol: str = pos["symbol"]
            qty: float  = pos["qty"]

            if qty == 0:
                continue

            # 获取最新评分（24h 内）
            score_record = await self._get_latest_score(account_id, symbol)
            if score_record is None:
                no_score_count += 1
                logger.debug(f"[RebalanceMonitor] {symbol}: no recent score, skip")
                continue

            # 强制转为 Python 原始类型，绕过 SQLAlchemy 列的静态推断
            recommendation: str = str(getattr(score_record, "recommendation", "HOLD") or "HOLD").upper()
            overall_val = getattr(score_record, "overall_score", 50)
            overall: int = int(overall_val) if overall_val is not None else 50

            # 只处理 REDUCE 和 SELL
            if recommendation not in ("REDUCE", "SELL"):
                details.append({
                    "symbol": symbol, "score": overall,
                    "recommendation": recommendation, "signal_created": None
                })
                continue

            # 检查是否已有待执行的 REDUCE/EXIT 信号
            if await self._has_pending_signal(account_id, symbol):
                already_pending += 1
                logger.debug(f"[RebalanceMonitor] {symbol}: pending signal already exists, skip")
                details.append({
                    "symbol": symbol, "score": overall,
                    "recommendation": recommendation, "signal_created": "SKIPPED_PENDING"
                })
                continue

            # 决定信号类型和数量
            if recommendation == "SELL" or overall <= _SCORE_SELL_THRESHOLD:
                signal_type = SignalType.EXIT
                quantity    = abs(qty)   # 全部清仓
                priority    = 85
            else:
                signal_type = SignalType.REDUCE
                quantity    = max(1.0, abs(qty) * _DEFAULT_REDUCE_RATIO)
                priority    = 65

            await self._create_signal(
                account_id  = account_id,
                symbol      = symbol,
                qty         = qty,
                quantity    = quantity,
                signal_type = signal_type,
                score       = overall,
                recommendation = recommendation,
                priority    = priority,
            )

            if signal_type == SignalType.EXIT:
                exit_count += 1
            else:
                reduce_count += 1

            details.append({
                "symbol": symbol,
                "score": overall,
                "recommendation": recommendation,
                "signal_created": signal_type.value,
                "quantity": quantity,
            })

            logger.info(
                f"[RebalanceMonitor] {signal_type.value} signal created: "
                f"{symbol} score={overall} qty={quantity:.0f}"
            )

        try:
            await self.session.commit()
        except Exception as e:
            logger.error(f"[RebalanceMonitor] DB commit failed: {e}")
            await self.session.rollback()

        return {
            "scanned": len(positions),
            "reduce_signals": reduce_count,
            "exit_signals": exit_count,
            "skipped_no_score": no_score_count,
            "skipped_already_pending": already_pending,
            "details": details,
        }

    # ─────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────

    async def _fetch_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """从 Broker 拉取当前持仓"""
        try:
            from app.broker.factory import make_option_broker_client
            from app.broker.dummy_option_client import DummyOptionClient

            broker = make_option_broker_client()
            if isinstance(broker, DummyOptionClient):
                logger.debug("[RebalanceMonitor] DummyClient — 跳过持仓拉取")
                return []

            raw = await broker.list_underlying_positions(account_id)
            result = []
            for p in raw:
                symbol = getattr(p, "symbol", None) or (p.get("symbol") if isinstance(p, dict) else None)
                qty    = getattr(p, "quantity", None) or (p.get("quantity") or p.get("qty") if isinstance(p, dict) else None)
                if symbol and qty:
                    result.append({"symbol": str(symbol).strip().upper(), "qty": float(qty)})
            return result
        except Exception as e:
            logger.error(f"[RebalanceMonitor] 持仓拉取失败: {e}")
            return []

    async def _get_latest_score(self, account_id: str, symbol: str) -> Optional[PositionScore]:
        """获取 24h 内最新的持仓评分"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_SCORE_VALID_HOURS)
        stmt = (
            select(PositionScore)
            .where(
                and_(
                    or_(
                        PositionScore.account_id == account_id,
                        PositionScore.account_id == "DEMO",  # 兼容默认 account_id
                    ),
                    PositionScore.symbol == symbol,
                    PositionScore.timestamp >= cutoff,
                )
            )
            .order_by(desc(PositionScore.timestamp))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _has_pending_signal(self, account_id: str, symbol: str) -> bool:
        """检查是否已有待执行的 REDUCE / EXIT 信号"""
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.symbol == symbol,
                TradingSignal.signal_type.in_([SignalType.REDUCE, SignalType.EXIT]),
                TradingSignal.status.in_([
                    SignalStatus.GENERATED,
                    SignalStatus.VALIDATED,
                    SignalStatus.QUEUED,
                    SignalStatus.EXECUTING,
                ]),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def _create_signal(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        quantity: float,
        signal_type: SignalType,
        score: int,
        recommendation: str,
        priority: int,
    ) -> TradingSignal:
        """创建 REDUCE / EXIT TradingSignal"""
        # 确定方向（多头减仓=SELL方向）
        direction = "LONG" if qty > 0 else "SHORT"

        signal = TradingSignal(
            signal_id         = str(uuid4()),
            account_id        = account_id,
            user_id           = account_id,   # 系统生成信号，user_id 复用 account_id
            symbol            = symbol,
            signal_type       = signal_type,
            signal_source     = SignalSource.RISK_MGMT,
            status            = SignalStatus.GENERATED,
            direction         = direction,
            quantity_mode     = "ABS_SHARES",
            quantity_value    = quantity,
            suggested_quantity= quantity,
            signal_strength   = max(0.1, (100 - score) / 100),  # 分数越低信号越强
            confidence        = max(0.1, (100 - score) / 100),
            risk_score        = (100 - score) / 100,
            priority          = priority,
            notes             = (
                f"AI 评分 {score}/100 (建议: {recommendation}) — "
                f"由 PositionRebalanceMonitor 自动生成"
            ),
            max_holding_days  = None,
            created_at        = datetime.utcnow(),
            extra_metadata    = {
                "closing_intent": signal_type.value,
                "execution_path": "FAST_CLOSE",
                "generated_by": "PositionRebalanceMonitor",
                "recommendation": recommendation,
                "current_position": {
                    "qty": abs(qty),
                    "price": None,
                },
            },
        )
        self.session.add(signal)
        return signal
