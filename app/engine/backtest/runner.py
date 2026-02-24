"""V10: BacktestRunner — 事件驱动回测引擎（支持 Walk-Forward）"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Any, cast

import numpy as np
import pandas as pd

from app.core.config import settings
from app.data.hub import data_hub

logger = logging.getLogger(__name__)

COMMISSION = settings.BACKTEST_COMMISSION_PCT
SLIPPAGE = settings.BACKTEST_SLIPPAGE_PCT


@dataclass
class Trade:
    symbol: str
    entry_date: date
    entry_price: float
    qty: float
    side: str  # BUY / SELL
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0


@dataclass
class BacktestState:
    cash: float
    positions: Dict[str, float] = field(default_factory=dict)  # symbol → qty
    avg_prices: Dict[str, float] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    dates: List[date] = field(default_factory=list)


class BacktestRunner:
    """事件驱动回测 + Walk-Forward 验证"""

    async def run(
        self,
        strategy_name: str,
        symbols: List[str],
        start: date,
        end: date,
        initial_capital: float = 100_000.0,
        walk_forward: bool = False,
    ) -> dict:
        """执行回测，返回绩效指标字典"""
        if walk_forward:
            return await self._walk_forward(
                strategy_name, symbols, start, end, initial_capital
            )
        return await self._single_run(
            strategy_name, symbols, start, end, initial_capital
        )

    # ──────────────────────────────────────────
    # 单次全量回测
    # ──────────────────────────────────────────

    async def _single_run(
        self,
        strategy_name: str,
        symbols: List[str],
        start: date,
        end: date,
        initial_capital: float,
    ) -> dict:
        # 1. 拉取历史数据
        price_data: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                price_data[sym] = await data_hub.get_ohlcv(sym, start, end)
            except Exception as e:
                logger.warning(f"Backtest: failed to fetch {sym}: {e}")

        if not price_data:
            raise ValueError("No price data available for any symbol")

        # 2. 生成日期序列（交集）
        all_dates = sorted(
            set.intersection(*[set(df.index) for df in price_data.values()])
        )

        # 3. 获取策略信号函数
        signal_fn = self._get_signal_fn(strategy_name)

        # 4. 事件回放
        state = BacktestState(cash=initial_capital)
        for dt in all_dates:
            prices = {sym: float(cast(Any, price_data[sym].loc[dt, "close"])) for sym in price_data if dt in price_data[sym].index}
            slices = {sym: price_data[sym].loc[:dt] for sym in price_data if dt in price_data[sym].index}

            signals = signal_fn(slices, state)  # {"AAPL": "BUY", "NVDA": "SELL", ...}

            for sym, action in signals.items():
                pr = prices.get(sym)
                if pr is None:
                    continue
                if action == "BUY" and sym not in state.positions:
                    # 等权重分配资金
                    alloc = state.cash * (1.0 / len(symbols))
                    cost = pr * (1 + SLIPPAGE + COMMISSION)
                    qty = alloc / cost
                    if qty > 0:
                        state.cash -= qty * cost
                        state.positions[sym] = qty
                        state.avg_prices[sym] = pr
                        state.trades.append(Trade(sym, dt, pr, qty, "BUY"))

                elif action == "SELL" and sym in state.positions:
                    qty = state.positions.pop(sym)
                    sell_pr = pr * (1 - SLIPPAGE - COMMISSION)
                    pnl = qty * (sell_pr - state.avg_prices.pop(sym, pr))
                    state.cash += qty * sell_pr
                    if state.trades and state.trades[-1].exit_date is None:
                        t = next((t for t in reversed(state.trades) if t.symbol == sym and t.exit_date is None), None)
                        if t:
                            t.exit_date = dt
                            t.exit_price = sell_pr
                            t.pnl = pnl

            # 每日权益
            mkt_value = sum(
                state.positions.get(sym, 0) * prices.get(sym, 0)
                for sym in state.positions
            )
            state.equity_curve.append(state.cash + mkt_value)
            state.dates.append(dt)

        # 5. 强制平仓
        if all_dates and state.positions:
            last_dt = all_dates[-1]
            last_prices = {sym: float(cast(Any, price_data[sym].loc[last_dt, "close"])) for sym in state.positions if last_dt in price_data.get(sym, pd.DataFrame()).index}
            for sym, qty in list(state.positions.items()):
                pr = last_prices.get(sym, 0)
                state.cash += qty * pr * (1 - COMMISSION)

        return self._calc_metrics(state, initial_capital)

    # ──────────────────────────────────────────
    # Walk-Forward 验证
    # ──────────────────────────────────────────

    async def _walk_forward(
        self,
        strategy_name: str,
        symbols: List[str],
        start: date,
        end: date,
        initial_capital: float,
    ) -> dict:
        """6个月 in-sample + 1个月 out-of-sample 滚动"""
        IS_MONTHS = 6
        OOS_MONTHS = 1
        results = []

        cur = start
        while cur < end:
            oos_start = cur + timedelta(days=IS_MONTHS * 30)
            oos_end = min(oos_start + timedelta(days=OOS_MONTHS * 30), end)
            if oos_start >= end:
                break
            try:
                r = await self._single_run(strategy_name, symbols, cur, oos_end, initial_capital)
                results.append(r)
            except Exception as e:
                logger.warning(f"WF slice {cur}-{oos_end} failed: {e}")
            cur = oos_start

        if not results:
            raise ValueError("Walk-forward produced no results")

        # 汇总各窗口均值
        avg = {}
        for k in ["annualized_return", "total_return", "sharpe", "sortino", "max_drawdown", "win_rate", "alpha"]:
            vals = [r.get(k, 0) for r in results if r.get(k) is not None]
            avg[k] = round(float(np.mean(vals)), 4) if vals else 0.0
        avg["walk_forward"] = True
        avg["windows"] = len(results)
        avg["windows_results"] = results  # V10: Include raw window results for report
        avg["graduation_eligible"] = self._check_graduation(avg)
        return avg

    # ──────────────────────────────────────────
    # 绩效计算
    # ──────────────────────────────────────────

    def _calc_metrics(self, state: BacktestState, initial_capital: float) -> dict:
        eq = np.array(state.equity_curve, dtype=float)
        if len(eq) < 2:
            return {"error": "insufficient data"}

        returns = np.diff(eq) / eq[:-1]
        total_return = (eq[-1] - initial_capital) / initial_capital
        n_days = len(returns)
        ann_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

        # Sharpe（无风险利率 4.5%）
        rf_daily = 0.045 / 252
        excess = returns - rf_daily
        sharpe = float(np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0.0

        # Sortino
        downside = excess[excess < 0]
        sortino = float(np.mean(excess) / np.std(downside) * np.sqrt(252)) if len(downside) > 0 and np.std(downside) > 0 else 0.0

        # Max Drawdown
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dd = float(np.min(dd))

        # Win Rate
        closed = [t for t in state.trades if t.exit_date]
        win_rate = len([t for t in closed if t.pnl > 0]) / max(len(closed), 1)

        # Alpha vs SPY（粗略：年化超额收益）
        alpha = round(ann_return - 0.10, 4)  # 假设 SPY 年化 ~10%

        result = {
            "annualized_return": round(ann_return, 4),
            "total_return": round(total_return, 4),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "alpha": alpha,
            "total_trades": len(closed),
            "equity_final": round(float(eq[-1]), 2),
        }
        result["graduation_eligible"] = self._check_graduation(result)
        return result

    def _check_graduation(self, result: dict) -> bool:
        """Paper→Live 毕业条件：Sharpe≥1.0 且 MaxDrawdown≤20% 且 WinRate≥50%"""
        return (
            result.get("sharpe", 0) >= 1.0
            and abs(result.get("max_drawdown", -1)) <= 0.20
            and result.get("win_rate", 0) >= 0.50
        )

    # ──────────────────────────────────────────
    # 策略信号适配器
    # ──────────────────────────────────────────

    def _get_signal_fn(self, strategy_name: str):
        """返回策略信号函数 fn(price_slices, state) → {symbol: action}"""
        name = strategy_name.lower().replace(" ", "_")

        if "bollinger" in name:
            return self._bollinger_signals
        elif "golden_cross" in name or "golden" in name:
            return self._golden_cross_signals
        elif "momentum" in name:
            return self._momentum_signals
        else:
            # 默认：简单动量
            return self._momentum_signals

    def _bollinger_signals(self, slices: Dict[str, pd.DataFrame], state: BacktestState) -> dict:
        signals = {}
        for sym, df in slices.items():
            if len(df) < 20:
                continue
            close = df["close"]
            sma = close.rolling(20).mean().iloc[-1]
            std = close.rolling(20).std().iloc[-1]
            last = close.iloc[-1]
            if last < sma - 2 * std:
                signals[sym] = "BUY"
            elif last > sma + 2 * std:
                signals[sym] = "SELL"
        return signals

    def _golden_cross_signals(self, slices: Dict[str, pd.DataFrame], state: BacktestState) -> dict:
        signals = {}
        for sym, df in slices.items():
            if len(df) < 50:
                continue
            close = df["close"]
            fast = close.rolling(10).mean()
            slow = close.rolling(50).mean()
            if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
                signals[sym] = "BUY"
            elif fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
                signals[sym] = "SELL"
        return signals

    def _momentum_signals(self, slices: Dict[str, pd.DataFrame], state: BacktestState) -> dict:
        signals = {}
        for sym, df in slices.items():
            if len(df) < 20:
                continue
            ret_20 = df["close"].iloc[-1] / df["close"].iloc[-20] - 1
            if ret_20 > 0.05 and sym not in state.positions:
                signals[sym] = "BUY"
            elif ret_20 < -0.03 and sym in state.positions:
                signals[sym] = "SELL"
        return signals


# 全局单例
backtest_runner = BacktestRunner()
