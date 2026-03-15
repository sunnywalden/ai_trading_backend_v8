"""V10.4.2: GhostTradeService — 幽灵交易服务

对被漏斗拒绝的信号进行无资金虚拟跟踪。
用于反事实验证：如果通过了漏斗，结果会是什么？

核心功能：
  1. create_from_rejected_signal() — 被拒后自动创建幽灵交易
  2. update_daily_prices()         — 每日收盘后更新价格/PnL（由 Job 驱动）
  3. get_ghost_trades()            — 获取幽灵交易列表（用于 Signal Watchtower）
  4. get_ghost_analysis()          — 幽灵胜率 vs 实际胜率对比分析
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ghost_trade import GhostTrade, GhostTradeResult

logger = logging.getLogger(__name__)


class GhostTradeService:
    """幽灵交易的 CRUD 及分析服务。"""

    async def create_from_rejected_signal(
        self,
        db: AsyncSession,
        *,
        symbol: str,
        signal_id: Optional[int],
        direction: str,
        rejection_reason: Optional[str],
        rejected_at_layer: Optional[int],
        conviction_at_rejection: Optional[float],
        entry_price: Optional[float] = None,  # 可选：由外部传入，否则需后续填充
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        max_tracking_days: int = 10,
    ) -> Optional[GhostTrade]:
        """为被拒绝的信号创建幽灵交易记录。

        若 entry_price 未提供（即没有价格快照），会创建占位记录，
        后续由 update_daily_prices() 在首次价格更新时补填。
        """
        try:
            trade = GhostTrade(
                signal_id=signal_id,
                symbol=symbol,
                direction=direction,
                rejection_reason=rejection_reason,
                rejected_at_layer=rejected_at_layer,
                conviction_score_at_rejection=conviction_at_rejection,
                entry_price=entry_price or 0.0,
                stop_loss=stop_loss,
                take_profit=take_profit,
                max_tracking_days=max_tracking_days,
                tracking_day=0,
                ghost_result=GhostTradeResult.OPEN,
                price_history=[],
                tracking_start=datetime.now(timezone.utc),
            )
            db.add(trade)
            await db.flush()
            logger.info(
                f"[GhostTrade] Created ghost trade for {symbol} {direction} "
                f"(rejected at layer {rejected_at_layer})"
            )
            return trade
        except Exception as e:
            logger.error(f"[GhostTrade] Failed to create ghost trade: {e}")
            return None

    async def update_daily_prices(
        self,
        db: AsyncSession,
        price_map: dict[str, float],  # symbol → 当日收盘价
    ) -> int:
        """
        每日收盘后批量更新处于 OPEN 状态的幽灵交易 PnL。

        Args:
            db:         DB session
            price_map:  {symbol: close_price} 字典

        Returns:
            更新条数
        """
        stmt = select(GhostTrade).where(
            GhostTrade.ghost_result == GhostTradeResult.OPEN
        )
        result = await db.execute(stmt)
        open_trades = result.scalars().all()

        updated = 0
        for trade in open_trades:
            close = price_map.get(trade.symbol)
            if close is None:
                continue

            # 第一次更新时补填 entry_price（若创建时未提供）
            if trade.entry_price == 0.0:
                trade.entry_price = close
                trade.stop_loss = close * (0.95 if trade.direction == "LONG" else 1.05)
                trade.take_profit = close * (
                    1.10 if trade.direction == "LONG" else 0.90
                )

            # 计算 PnL
            if trade.direction == "LONG":
                pnl_pct = (close - trade.entry_price) / trade.entry_price
            else:
                pnl_pct = (trade.entry_price - close) / trade.entry_price

            nominal = 100.0  # 100 单位名义
            pnl_abs = nominal * pnl_pct

            # 更新最高/最低价
            if trade.highest_price is None or close > trade.highest_price:
                trade.highest_price = close
            if trade.lowest_price is None or close < trade.lowest_price:
                trade.lowest_price = close

            # 追加价格历史
            history: list[dict] = list(trade.price_history or [])
            history.append(
                {
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "close": close,
                    "pnl_pct": round(pnl_pct * 100, 2),
                }
            )
            trade.price_history = history[-trade.max_tracking_days :]

            # 更新状态
            trade.last_price = close
            trade.ghost_pnl_pct = round(pnl_pct * 100, 2)
            trade.ghost_pnl_abs = round(pnl_abs, 2)
            trade.tracking_day += 1

            # 判断结束条件
            if trade.stop_loss and trade.take_profit:
                if trade.direction == "LONG":
                    if close <= trade.stop_loss:
                        trade.ghost_result = GhostTradeResult.LOSS
                        trade.tracking_end = datetime.now(timezone.utc)
                    elif close >= trade.take_profit:
                        trade.ghost_result = GhostTradeResult.WIN
                        trade.tracking_end = datetime.now(timezone.utc)
                else:
                    if close >= trade.stop_loss:
                        trade.ghost_result = GhostTradeResult.LOSS
                        trade.tracking_end = datetime.now(timezone.utc)
                    elif close <= trade.take_profit:
                        trade.ghost_result = GhostTradeResult.WIN
                        trade.tracking_end = datetime.now(timezone.utc)

            if (
                trade.tracking_day >= trade.max_tracking_days
                and trade.ghost_result == GhostTradeResult.OPEN
            ):
                trade.ghost_result = GhostTradeResult.EXPIRED
                trade.tracking_end = datetime.now(timezone.utc)
                # EXPIRED 视为 PnL > 0 则 WIN，否则 LOSS
                if (trade.ghost_pnl_pct or 0) > 0:
                    trade.ghost_result = GhostTradeResult.WIN
                else:
                    trade.ghost_result = GhostTradeResult.LOSS

            updated += 1

        await db.flush()
        logger.info(f"[GhostTrade] Updated {updated} open ghost trades")
        return updated

    async def get_ghost_trades(
        self,
        db: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
        ghost_result: Optional[str] = None,
        symbol: Optional[str] = None,
        since_days: int = 30,
        account_id: Optional[str] = None,
    ) -> list[dict]:
        """获取幽灵交易列表。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions = [GhostTrade.tracking_start >= cutoff]
        if ghost_result:
            conditions.append(GhostTrade.ghost_result == ghost_result)
        if symbol:
            conditions.append(GhostTrade.symbol == symbol)
        if account_id and settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED:
            from app.models.trading_signal import TradingSignal

            conditions.append(
                GhostTrade.signal_id.in_(
                    select(TradingSignal.id).where(
                        TradingSignal.account_id == account_id
                    )
                )
            )

        stmt = (
            select(GhostTrade)
            .where(and_(*conditions))
            .order_by(GhostTrade.tracking_start.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(r) for r in rows]

    async def get_ghost_analysis(
        self,
        db: AsyncSession,
        *,
        since_days: int = 30,
        account_id: Optional[str] = None,
    ) -> dict:
        """
        幽灵交易分析：对比幽灵胜率 vs 实际信号胜率。

        也计算按拒绝层级/原因的胜率分布，
        帮助判断漏斗参数是否过松或过严。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions = [
            GhostTrade.tracking_start >= cutoff,
            GhostTrade.ghost_result.in_([GhostTradeResult.WIN, GhostTradeResult.LOSS]),
        ]
        if account_id and settings.ACCOUNT_DATA_ISOLATION_V1131_ENABLED:
            from app.models.trading_signal import TradingSignal

            conditions.append(
                GhostTrade.signal_id.in_(
                    select(TradingSignal.id).where(
                        TradingSignal.account_id == account_id
                    )
                )
            )

        stmt = select(GhostTrade).where(and_(*conditions))
        result = await db.execute(stmt)
        closed_trades = result.scalars().all()

        total = len(closed_trades)
        wins = sum(1 for t in closed_trades if t.ghost_result == GhostTradeResult.WIN)
        win_rate = round(wins / max(1, total) * 100, 1)
        avg_pnl = sum(t.ghost_pnl_pct or 0 for t in closed_trades) / max(1, total)

        # 按拒绝层级的胜率
        layer_stats: dict[str, dict] = {}
        for t in closed_trades:
            layer_key = f"layer_{t.rejected_at_layer}"
            if layer_key not in layer_stats:
                layer_stats[layer_key] = {"total": 0, "wins": 0}
            layer_stats[layer_key]["total"] += 1
            if t.ghost_result == GhostTradeResult.WIN:
                layer_stats[layer_key]["wins"] += 1
        for k in layer_stats:
            d = layer_stats[k]
            d["win_rate_pct"] = round(d["wins"] / max(1, d["total"]) * 100, 1)

        # 按拒绝原因的胜率
        reason_stats: dict[str, dict] = {}
        for t in closed_trades:
            key = t.rejection_reason or "UNKNOWN"
            if key not in reason_stats:
                reason_stats[key] = {"total": 0, "wins": 0}
            reason_stats[key]["total"] += 1
            if t.ghost_result == GhostTradeResult.WIN:
                reason_stats[key]["wins"] += 1
        for k in reason_stats:
            d = reason_stats[k]
            d["win_rate_pct"] = round(d["wins"] / max(1, d["total"]) * 100, 1)

        # 获取实际推进信号的胜率（对比用）
        real_win_rate = await self._get_real_signal_win_rate(db, since_days)

        # 诊断结论
        if real_win_rate is not None:
            gap = win_rate - real_win_rate
            if gap > 10:
                conclusion = (
                    f"⚠️ 幽灵胜率({win_rate}%) 高于实际信号胜率({real_win_rate}%) 超过 10%，"
                    f"漏斗可能过严，建议适当降低门槛"
                )
            elif gap < -10:
                conclusion = (
                    f"✅ 幽灵胜率({win_rate}%) 低于实际信号胜率({real_win_rate}%) 超过 10%，"
                    f"漏斗效果优秀，精选策略正在发挥作用"
                )
            else:
                conclusion = (
                    f"📊 幽灵胜率({win_rate}%) 与实际信号胜率({real_win_rate}%) 接近，"
                    f"漏斗参数趋于合理，可继续观察"
                )
        else:
            conclusion = f"幽灵胜率: {win_rate}%（实际胜率数据不足，无法对比）"

        return {
            "since_days": since_days,
            "ghost_total": total,
            "ghost_wins": wins,
            "ghost_win_rate_pct": win_rate,
            "ghost_avg_pnl_pct": round(avg_pnl, 2),
            "real_win_rate_pct": real_win_rate,
            "win_rate_gap_pct": round(win_rate - (real_win_rate or win_rate), 1),
            "layer_breakdown": layer_stats,
            "reason_breakdown": reason_stats,
            "conclusion": conclusion,
            "recommendation": (
                "LOOSEN_THRESHOLD"
                if (real_win_rate and win_rate - real_win_rate > 10)
                else (
                    "MAINTAIN"
                    if (real_win_rate and abs(win_rate - real_win_rate) <= 10)
                    else "TIGHTEN_THRESHOLD"
                )
            ),
        }

    async def _get_real_signal_win_rate(
        self,
        db: AsyncSession,
        since_days: int,
    ) -> Optional[float]:
        """从 trade_attribution_entries 获取最近 N 天的实际信号胜率。"""
        try:
            from app.models.trade_attribution import (
                AttributionCategory,
                TradeAttributionEntry,
            )

            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
            stmt = select(
                func.count().label("total"),
                func.sum(
                    func.if_(
                        TradeAttributionEntry.category == AttributionCategory.WIN, 1, 0
                    )
                ).label("wins"),
            ).where(TradeAttributionEntry.created_at >= cutoff)
            row = (await db.execute(stmt)).one_or_none()
            if row and row[0] and row[0] > 5:
                return round(int(row[1] or 0) / row[0] * 100, 1)
        except Exception as e:
            logger.debug(f"[GhostTrade] get real win rate failed: {e}")
        return None

    def _row_to_dict(self, r: GhostTrade) -> dict:
        return {
            "id": r.id,
            "signal_id": r.signal_id,
            "symbol": r.symbol,
            "direction": r.direction,
            "rejection_reason": r.rejection_reason,
            "rejected_at_layer": r.rejected_at_layer,
            "conviction_score_at_rejection": r.conviction_score_at_rejection,
            "entry_price": r.entry_price,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "last_price": r.last_price,
            "ghost_pnl_pct": r.ghost_pnl_pct,
            "ghost_pnl_abs": r.ghost_pnl_abs,
            "ghost_result": r.ghost_result,
            "tracking_day": r.tracking_day,
            "max_tracking_days": r.max_tracking_days,
            "price_history": r.price_history,
            "tracking_start": (
                r.tracking_start.isoformat() if r.tracking_start else None
            ),
            "tracking_end": r.tracking_end.isoformat() if r.tracking_end else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }


# ── 模块级单例 ────────────────────────────────────────────────────────────────
ghost_trade_service = GhostTradeService()
ghost_trade_service = GhostTradeService()
