"""
持仓主动监控器 — P0/P1 核心组件

职责:
  1. 定期拉取账户当前持仓（来自 Tiger Broker 或 Dummy）
  2. 通过 DataHub 获取最新价格
  3. 计算每笔持仓的浮盈/浮亏百分比
  4. 对触发 止损 / 止盈 / 最大持仓天数 的标的写入 EXIT 信号
  5. 同时更新 AutonomousEngine 的持仓感知数据（喂给 AI 决策上下文）

外部依赖:
  - app.broker.factory.make_option_broker_client
  - app.data.hub.data_hub
  - app.models.trading_signal.TradingSignal (写 EXIT 信号)
  - app.core.config.settings (止损/止盈阈值)
  - app.core.market_hours.is_symbol_market_active (交易时段校验)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, cast
from uuid import uuid4

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.market_hours import is_symbol_market_active
from app.models.trading_signal import (
    TradingSignal, SignalType, SignalStatus, SignalSource,
)

logger = logging.getLogger(__name__)


class PositionExitReason:
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAX_HOLDING_DAYS = "MAX_HOLDING_DAYS"
    TECHNICAL_REVERSAL = "TECHNICAL_REVERSAL"


class PositionMonitor:
    """
    主动持仓扫描器：每次调用 scan() 完成一轮全仓检查。
    检查项（按优先级）：
      1. 止损  ：unrealized_pnl_pct <= -POSITION_STOP_LOSS_PCT   → 高优先级 EXIT
      2. 止盈  ：unrealized_pnl_pct >= +POSITION_TAKE_PROFIT_PCT → 中优先级 EXIT
      3. 超龄  ：holding_days >= stop_loss_price（此处复用为 max_holding_days）
                 注：实际上从原 TradingSignal.max_holding_days 读取，缺省 30 天
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def scan(self, account_id: str) -> Dict[str, Any]:
        """
        主入口：扫描当前持仓，生成必要的 EXIT 信号。

        Returns:
            {
                "scanned_positions": int,
                "exit_signals_generated": int,
                "skipped_no_market": int,
                "details": [{"symbol": ..., "reason": ..., "pnl_pct": ...}, ...]
            }
        """
        positions = await self._fetch_positions(account_id)
        if not positions:
            logger.debug(f"[PositionMonitor] No positions for {account_id}")
            return {
                "scanned_positions": 0,
                "exit_signals_generated": 0,
                "skipped_no_market": 0,
                "details": [],
            }

        exit_count = 0
        skipped = 0
        details: List[Dict[str, Any]] = []

        for pos in positions:
            symbol: str = pos.get("symbol", "")
            if not symbol:
                continue

            # 只在对应市场活跃时段扫描
            if not is_symbol_market_active(symbol):
                skipped += 1
                logger.debug(f"[PositionMonitor] {symbol} market inactive, skipping")
                continue

            qty: float = float(pos.get("qty", 0))
            avg_cost: float = float(pos.get("avg_cost", 0))
            if qty == 0 or avg_cost == 0:
                continue

            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            if current_price is None or current_price <= 0:
                logger.debug(f"[PositionMonitor] Cannot get price for {symbol}, skipping")
                continue

            unrealized_pnl_pct = (current_price - avg_cost) / avg_cost
            # 空头持仓取反
            if qty < 0:
                unrealized_pnl_pct = -unrealized_pnl_pct

            # 查找原始开仓信号（获取 max_holding_days）
            original_signal = await self._find_entry_signal(account_id, symbol)
            _mhd = cast(Any, original_signal.max_holding_days) if original_signal else None
            max_holding_days: int = int(_mhd) if _mhd else 30
            holding_days = self._calc_holding_days(original_signal)

            # ---------- 触发条件检查 ----------
            exit_reason: Optional[str] = None
            priority = 50

            if unrealized_pnl_pct <= -settings.POSITION_STOP_LOSS_PCT:
                exit_reason = PositionExitReason.STOP_LOSS
                priority = 95
            elif unrealized_pnl_pct >= settings.POSITION_TAKE_PROFIT_PCT:
                exit_reason = PositionExitReason.TAKE_PROFIT
                priority = 80
            elif holding_days is not None and holding_days >= max_holding_days:
                exit_reason = PositionExitReason.MAX_HOLDING_DAYS
                priority = 70

            if exit_reason:
                already_pending = await self._has_pending_exit(account_id, symbol)
                if not already_pending:
                    await self._create_exit_signal(
                        account_id=account_id,
                        symbol=symbol,
                        qty=qty,
                        current_price=current_price,
                        exit_reason=exit_reason,
                        unrealized_pnl_pct=unrealized_pnl_pct,
                        priority=priority,
                        original_signal=original_signal,
                    )
                    exit_count += 1
                    logger.info(
                        f"[PositionMonitor] EXIT signal created: {symbol} "
                        f"reason={exit_reason} pnl_pct={unrealized_pnl_pct:.2%}"
                    )

                details.append({
                    "symbol": symbol,
                    "reason": exit_reason,
                    "pnl_pct": round(unrealized_pnl_pct, 4),
                    "holding_days": holding_days,
                    "current_price": current_price,
                    "avg_cost": avg_cost,
                    "already_pending": already_pending if exit_reason else False,
                })

        try:
            await self.session.commit()
        except Exception as e:
            logger.error(f"[PositionMonitor] DB commit failed: {e}")

        return {
            "scanned_positions": len(positions),
            "exit_signals_generated": exit_count,
            "skipped_no_market": skipped,
            "details": details,
        }

    # ──────────────────────────────────────────────────────────────
    # 持仓拉取
    # ──────────────────────────────────────────────────────────────

    async def _fetch_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """从 Broker 拉取持仓列表"""
        try:
            from app.broker.factory import make_option_broker_client
            broker = make_option_broker_client()

            from app.broker.dummy_option_client import DummyOptionClient
            if isinstance(broker, DummyOptionClient):
                logger.debug("[PositionMonitor] DummyClient active — no real positions")
                return []

            raw_positions = await broker.list_underlying_positions(account_id)
            result = []
            for p in raw_positions:
                symbol = getattr(p, "symbol", None) or (p.get("symbol") if isinstance(p, dict) else None)
                qty = getattr(p, "quantity", None) or (p.get("quantity") or p.get("qty") if isinstance(p, dict) else None)
                avg_price = getattr(p, "average_cost", None) or (
                    p.get("average_cost") or p.get("avg_price") or p.get("avg_cost")
                    if isinstance(p, dict) else None
                )
                if symbol and qty:
                    result.append({
                        "symbol": str(symbol),
                        "qty": float(qty),
                        "avg_cost": float(avg_price or 0),
                    })
            return result
        except Exception as e:
            logger.warning(f"[PositionMonitor] Failed to fetch positions: {e}")
            return []

    # ──────────────────────────────────────────────────────────────
    # 价格获取
    # ──────────────────────────────────────────────────────────────

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """通过 DataHub 获取最新价格"""
        try:
            from app.data.hub import data_hub
            quote = await data_hub.get_quote(symbol)
            price = quote.get("price")
            return float(price) if price is not None else None
        except Exception as e:
            logger.debug(f"[PositionMonitor] Price fetch failed for {symbol}: {e}")
            return None

    # ──────────────────────────────────────────────────────────────
    # 原始开仓信号查询
    # ──────────────────────────────────────────────────────────────

    async def _find_entry_signal(
        self, account_id: str, symbol: str
    ) -> Optional[TradingSignal]:
        """查找该仓位最近的 ENTRY / ADD 信号（用于获取 max_holding_days 等元数据）"""
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.symbol == symbol,
                    TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
                    TradingSignal.status == SignalStatus.EXECUTED,
                )
            )
            .order_by(TradingSignal.executed_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _has_pending_exit(self, account_id: str, symbol: str) -> bool:
        """检查是否已有待执行的 EXIT 信号（避免重复写入）"""
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.symbol == symbol,
                    TradingSignal.signal_type == SignalType.EXIT,
                    TradingSignal.status.in_([
                        SignalStatus.GENERATED, SignalStatus.VALIDATED, SignalStatus.QUEUED
                    ]),
                    or_(
                        TradingSignal.expired_at.is_(None),
                        TradingSignal.expired_at > datetime.utcnow(),
                    ),
                )
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    # ──────────────────────────────────────────────────────────────
    # EXIT 信号写入
    # ──────────────────────────────────────────────────────────────

    async def _create_exit_signal(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        current_price: float,
        exit_reason: str,
        unrealized_pnl_pct: float,
        priority: int,
        original_signal: Optional[TradingSignal],
    ) -> TradingSignal:
        """写入一条 EXIT 信号"""
        direction = "LONG"
        user_id = ""
        strategy_id = None
        strategy_run_id = None

        if original_signal:
            direction = original_signal.direction or "LONG"
            user_id = original_signal.user_id or ""
            strategy_id = original_signal.strategy_id
            strategy_run_id = original_signal.strategy_run_id

        signal = TradingSignal(
            signal_id=str(uuid4()),
            signal_type=SignalType.EXIT,
            signal_source=SignalSource.RISK_MGMT,
            status=SignalStatus.GENERATED,
            symbol=symbol,
            direction=direction,
            signal_strength=float(priority),
            confidence=min(priority / 100.0, 1.0),
            expected_return=unrealized_pnl_pct,      # 锁定当前浮盈/浮亏
            risk_score=90.0 if exit_reason == PositionExitReason.STOP_LOSS else 50.0,
            suggested_quantity=abs(qty),
            quantity_mode="ABS_SHARES",
            quantity_value=abs(qty),
            suggested_price=current_price,
            strategy_id=strategy_id,
            strategy_run_id=strategy_run_id,
            account_id=account_id,
            user_id=user_id,
            priority=priority,
            expired_at=datetime.utcnow() + timedelta(hours=4),  # EXIT 信号 4 小时有效
            extra_metadata={
                "exit_reason": exit_reason,
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 4),
                "current_price": current_price,
                "trigger_threshold": (
                    -settings.POSITION_STOP_LOSS_PCT
                    if exit_reason == PositionExitReason.STOP_LOSS
                    else settings.POSITION_TAKE_PROFIT_PCT
                ),
                "original_signal_id": original_signal.signal_id if original_signal else None,
                "generated_by": "PositionMonitor",
            },
        )
        self.session.add(signal)
        return signal

    # ──────────────────────────────────────────────────────────────
    # 持仓天数计算
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_holding_days(signal: Optional[TradingSignal]) -> Optional[int]:
        if signal and cast(Any, signal.executed_at):
            return (datetime.utcnow() - cast(Any, signal.executed_at)).days
        return None

    # ──────────────────────────────────────────────────────────────
    # 持仓快照（供 AutonomousEngine._get_daily_stats 调用）
    # ──────────────────────────────────────────────────────────────

    async def get_positions_snapshot(self, account_id: str) -> Dict[str, Dict[str, Any]]:
        """
        返回 {symbol: {"qty": ..., "avg_cost": ..., "current_price": ..., "unrealized_pnl_pct": ...}}
        供 AI 决策引擎感知持仓状态。
        """
        positions = await self._fetch_positions(account_id)
        snapshot: Dict[str, Dict[str, Any]] = {}
        for pos in positions:
            symbol = pos["symbol"]
            qty = pos["qty"]
            avg_cost = pos["avg_cost"]
            price = await self._get_current_price(symbol)
            pnl_pct = (
                ((price - avg_cost) / avg_cost) if price and avg_cost else 0.0
            )
            if qty < 0:
                pnl_pct = -pnl_pct
            snapshot[symbol] = {
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": price,
                "unrealized_pnl_pct": round(pnl_pct, 4),
            }
        return snapshot
