from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.broker.history_factory import make_trade_history_client
from app.broker.history_models import TradeRecord
from app.models.symbol_behavior_stats import SymbolBehaviorStats


@dataclass
class SymbolBehaviorMetrics:
    symbol: str
    trade_count: int
    sell_fly_events: int
    sell_fly_extra_cost_ratio: float
    overtrade_index: float
    revenge_events: int

    behavior_score: int
    sell_fly_score: int
    overtrade_score: int
    revenge_score: int


class BehaviorScoringService:
    """行为评分引擎：直接从老虎历史成交 & 盈亏数据计算行为评分。

    目标：
    - 针对每个标的（symbol）分析：
        * 卖飞行为：低位卖出后又在更高价买回、或频繁止盈后追高回补
        * 过度交易：在短时间内频繁进出、持仓周期极短
        * 报复性交易：大额亏损后短时间内放大仓位再次冲入
    - 给出行为评分（0~100）并写回 symbol_behavior_stats 表，供风控和 AI 使用。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.history_client = make_trade_history_client()

    # -------- 对外主入口 --------

    async def run_for_account(
        self,
        account_id: str,
        window_days: int = 60,
        as_of: datetime | None = None,
    ) -> Dict[str, SymbolBehaviorMetrics]:
        """对指定账户，在最近 window_days 内计算行为评分并落库。

        返回：symbol -> SymbolBehaviorMetrics
        """
        if as_of is None:
            as_of = datetime.utcnow()
        start = as_of - timedelta(days=window_days)

        trades = await self.history_client.list_trades(account_id, start, as_of)
        if not trades:
            return {}

        trades_by_symbol: Dict[str, List[TradeRecord]] = {}
        for tr in trades:
            trades_by_symbol.setdefault(tr.symbol, []).append(tr)

        metrics_map: Dict[str, SymbolBehaviorMetrics] = {}
        for symbol, symbol_trades in trades_by_symbol.items():
            symbol_trades.sort(key=lambda t: t.timestamp)
            metrics = self._compute_metrics_for_symbol(symbol, symbol_trades, window_days)
            metrics_map[symbol] = metrics
            await self._upsert_stats_row(account_id, window_days, metrics)

        await self.session.commit()
        return metrics_map

    # -------- 计算逻辑 --------

    def _compute_metrics_for_symbol(
        self,
        symbol: str,
        trades: List[TradeRecord],
        window_days: int,
    ) -> SymbolBehaviorMetrics:
        trade_count = len(trades)
        if trade_count == 0:
            return SymbolBehaviorMetrics(
                symbol=symbol,
                trade_count=0,
                sell_fly_events=0,
                sell_fly_extra_cost_ratio=0.0,
                overtrade_index=0.0,
                revenge_events=0,
                behavior_score=50,
                sell_fly_score=50,
                overtrade_score=50,
                revenge_score=50,
            )

        # 1) 卖飞：卖出后 N 日内以更高价格买回的行为
        sell_fly_events, extra_cost_ratio = self._compute_sell_fly(trades)

        # 2) 过度交易指数：单位时间的成交频次 + 持仓周期近似
        overtrade_index = self._compute_overtrade_index(trades, window_days)

        # 3) 报复性交易：大额亏损后短时间内加倍冲入
        revenge_events = self._compute_revenge_events(trades)

        # 4) 将指标映射为评分 (0~100, 越高越稳健)
        sell_fly_score = self._score_sell_fly(extra_cost_ratio, sell_fly_events)
        overtrade_score = self._score_overtrade(overtrade_index, trade_count)
        revenge_score = self._score_revenge(revenge_events)

        # 综合行为评分：可根据你偏好调整权重
        behavior_score = int(
            0.4 * sell_fly_score
            + 0.3 * overtrade_score
            + 0.3 * revenge_score
        )

        return SymbolBehaviorMetrics(
            symbol=symbol,
            trade_count=trade_count,
            sell_fly_events=sell_fly_events,
            sell_fly_extra_cost_ratio=extra_cost_ratio,
            overtrade_index=overtrade_index,
            revenge_events=revenge_events,
            behavior_score=behavior_score,
            sell_fly_score=sell_fly_score,
            overtrade_score=overtrade_score,
            revenge_score=revenge_score,
        )

    def _compute_sell_fly(self, trades: List[TradeRecord]) -> Tuple[int, float]:
        """卖飞定义（基于历史成交）：

        - 在平掉/减仓后短时间内（这里用 window 内）又以更高价格买回；
        - 额外多付的价差 * 股数 / 总成交金额，作为卖飞成本率。

        我们不引入外部行情，只使用成交数据：
        - 对于 SELL -> 后续 BUY 且 buy_price > sell_price 的部分，认定为卖飞事件。
        """
        # 简单近似：用全窗口，不再额外按时间窗口截断
        sells = [t for t in trades if t.side == "SELL"]
        buys = [t for t in trades if t.side == "BUY"]

        if not sells or not buys:
            return 0, 0.0

        sell_fly_events = 0
        extra_cost_total = 0.0
        traded_notional_total = 0.0

        # 记录总成交金额用于归一化
        for t in trades:
            traded_notional_total += abs(t.quantity) * t.price

        # 用简单 O(n^2) 算法即可，后续如需可优化
        for s in sells:
            for b in buys:
                if b.timestamp <= s.timestamp:
                    continue
                if b.price <= s.price:
                    continue
                # 在 window 内卖出后又更高价买回，记为卖飞
                qty = min(abs(s.quantity), abs(b.quantity))
                sell_fly_events += 1
                extra_cost_total += (b.price - s.price) * qty
                break  # 同一卖出只匹配一次

        if traded_notional_total <= 0:
            return sell_fly_events, 0.0

        extra_cost_ratio = extra_cost_total / traded_notional_total
        return sell_fly_events, extra_cost_ratio

    def _compute_overtrade_index(self, trades: List[TradeRecord], window_days: int) -> float:
        """过度交易指数：

        简化定义：
        - trade_count_per_day = 交易笔数 / window_days
        - 对于极高频交易（比如 > 10 笔/天），视为严重过度交易；
        - 只做粗略刻画即可，精细版可以引入“持仓天数”“换手率”等。
        """
        trade_count = len(trades)
        if window_days <= 0:
            return float(trade_count)
        return trade_count / float(window_days)

    def _compute_revenge_events(self, trades: List[TradeRecord]) -> int:
        """报复性交易识别（基于成交和单笔盈亏）：

        逻辑近似：
        - 如果一笔成交的 realized_pnl 显著为负（亏损超过 notional 的 2%~3%），
        - 且在之后短时间窗口内（例如 1 天）在同一标的上明显放大仓位买入，
          则视为一次报复性交易。
        """
        # 为了简单，这里只基于 realized_pnl 标记“严重亏损”事件，
        # 再看后续 1 日内是否存在放大买入。
        revenge_events = 0
        if not trades:
            return 0

        # 先粗略计算单笔 notional
        for i, t in enumerate(trades):
            if t.realized_pnl is None:
                continue
            notional = abs(t.quantity) * t.price
            if notional <= 0:
                continue
            loss_ratio = t.realized_pnl / notional
            if loss_ratio >= -0.03:  # 亏损小于 3% 不算严重
                continue

            # 查找接下来 1 日内是否有明显放大买入
            cutoff = t.timestamp + timedelta(days=1)
            base_size = abs(t.quantity)
            for j in range(i + 1, len(trades)):
                nxt = trades[j]
                if nxt.timestamp > cutoff:
                    break
                if nxt.side != "BUY":
                    continue
                if abs(nxt.quantity) >= 1.5 * base_size:
                    revenge_events += 1
                    break

        return revenge_events

    # -------- 指标 → 评分 映射 --------

    def _score_sell_fly(self, extra_cost_ratio: float, events: int) -> int:
        """卖飞评分：越低越经常卖飞。"""
        # 按“卖飞成本占总成交额比例”粗略映射
        r = max(0.0, extra_cost_ratio)
        if events == 0:
            return 85
        if r <= 0.01:
            return 80
        if r <= 0.03:
            return 70
        if r <= 0.06:
            return 60
        if r <= 0.10:
            return 50
        return 40

    def _score_overtrade(self, overtrade_index: float, trade_count: int) -> int:
        """过度交易评分：指数越高，评分越低。"""
        # overtrade_index = 笔数 / 天数
        x = overtrade_index
        if trade_count <= 2:
            return 85
        if x <= 0.5:
            return 80
        if x <= 1.0:
            return 70
        if x <= 2.0:
            return 60
        if x <= 5.0:
            return 50
        return 40

    def _score_revenge(self, revenge_events: int) -> int:
        if revenge_events == 0:
            return 85
        if revenge_events == 1:
            return 70
        if revenge_events == 2:
            return 60
        return 45

    # -------- 持久化到 symbol_behavior_stats --------

    async def _upsert_stats_row(
        self,
        account_id: str,
        window_days: int,
        m: SymbolBehaviorMetrics,
    ) -> None:
        """将计算结果写入 symbol_behavior_stats 表。

        规则：
        - (account_id, symbol, window_days) 做唯一逻辑主键
        - 若存在则更新，若不存在则插入
        - 其他未填写字段使用默认值（0 或数据库默认）
        """
        stmt = select(SymbolBehaviorStats).where(
            SymbolBehaviorStats.account_id == account_id,
            SymbolBehaviorStats.symbol == m.symbol,
            SymbolBehaviorStats.window_days == window_days,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = SymbolBehaviorStats(
                account_id=account_id,
                symbol=m.symbol,
                window_days=window_days,
            )
            self.session.add(row)

        row.trade_count = m.trade_count
        # 原始行为指标（用于前端展示）
        row.sell_fly_events = m.sell_fly_events
        row.sell_fly_extra_cost_ratio = m.sell_fly_extra_cost_ratio
        row.overtrade_index = m.overtrade_index
        row.revenge_events = m.revenge_events

        # 评分结果（用于风控与 AI 决策）
        row.overtrade_score = m.overtrade_score
        row.revenge_trade_score = m.revenge_score
        row.behavior_score = m.behavior_score
        row.sell_fly_score = m.sell_fly_score
        # 其他字段（avg_holding_days 等）可在后续
# 版本中逐步完善
