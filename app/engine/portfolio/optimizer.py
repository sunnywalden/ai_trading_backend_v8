"""V10: PortfolioOptimizer — Markowitz + Risk Parity + Kelly"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Any, cast

import numpy as np
import pandas as pd

from app.data.hub import data_hub

logger = logging.getLogger(__name__)

HALF_KELLY = 0.5
MAX_SINGLE_WEIGHT = 0.25  # Kelly 单标的上限


class PortfolioOptimizer:
    """投资组合优化器（支持 Markowitz / Risk Parity / Kelly）"""

    async def optimize(
        self,
        symbols: List[str],
        method: str = "MARKOWITZ",
        lookback_days: int = 252,
        current_weights: Optional[Dict[str, float]] = None,
        risk_free_rate: float = 0.04,
    ) -> dict:
        """
        返回:
          - target_weights: 优化权重字典
          - current_weights: 当前权重（传入，若未传则全 0）
          - frontier_data: 有效前沿散点（仅 Markowitz）
          - expected_return: 预期年化收益
          - expected_volatility: 预期年化波动率
          - sharpe_ratio: 优化后 Sharpe
        """
        end = date.today()
        start = end - timedelta(days=lookback_days)

        # 拉取历史收益率
        returns = await self._fetch_returns(symbols, start, end)
        if returns.empty or returns.shape[1] < 2:
            raise ValueError("Insufficient return data for optimization")

        current_weights = current_weights or {sym: 0.0 for sym in symbols}

        if method == "MARKOWITZ":
            return await asyncio.to_thread(
                self._markowitz, returns, symbols, current_weights, risk_free_rate
            )
        elif method == "RISK_PARITY":
            return await asyncio.to_thread(
                self._risk_parity, returns, symbols, current_weights, risk_free_rate
            )
        elif method == "KELLY":
            return await asyncio.to_thread(
                self._kelly, returns, symbols, current_weights, risk_free_rate
            )
        else:
            raise ValueError(f"Unknown optimization method: {method}")

    # ──────────────────────────────────────────
    # Markowitz 均值方差优化
    # ──────────────────────────────────────────

    def _markowitz(
        self, returns: pd.DataFrame, symbols: List[str], current_weights: dict, rf: float = 0.04
    ) -> dict:
        from scipy.optimize import minimize

        mu = returns.mean() * 252
        cov = returns.cov() * 252
        n = len(symbols)

        def neg_sharpe(w):
            port_ret = w @ mu.values
            port_vol = np.sqrt(w @ cov.values @ w)
            return -(port_ret - rf) / port_vol if port_vol > 0 else 0

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.0, MAX_SINGLE_WEIGHT)] * n
        w0 = np.ones(n) / n

        result = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        opt_w = result.x if result.success else w0

        # 有效前沿采样（50个点）
        frontier = []
        for target_ret in np.linspace(float(cast(Any, mu.min())), float(cast(Any, mu.max())), 50):
            cons = constraints + [{"type": "eq", "fun": lambda w, r=target_ret: cast(Any, w) @ cast(Any, mu.values) - r}]
            res = minimize(lambda w: cast(Any, w) @ cast(Any, cov.values) @ cast(Any, w), w0, method="SLSQP", bounds=bounds, constraints=cons)
            if res.success:
                vol = np.sqrt(res.fun)
                frontier.append({"return": round(target_ret, 4), "volatility": round(vol, 4)})

        port_ret = float(cast(Any, opt_w) @ cast(Any, mu.values))
        port_vol = float(np.sqrt(cast(Any, opt_w) @ cast(Any, cov.values) @ cast(Any, opt_w)))
        sharpe = (port_ret - rf) / port_vol if port_vol > 0 else 0.0

        return {
            "target_weights": {sym: round(float(cast(Any, w)), 4) for sym, w in zip(symbols, opt_w)},
            "current_weights": current_weights,
            "frontier_data": frontier,
            "expected_return": round(port_ret, 4),
            "expected_volatility": round(port_vol, 4),
            "sharpe_ratio": round(sharpe, 4),
            "method": "MARKOWITZ",
        }

    # ──────────────────────────────────────────
    # Risk Parity（等风险贡献）
    # ──────────────────────────────────────────

    def _risk_parity(
        self, returns: pd.DataFrame, symbols: List[str], current_weights: dict, rf: float = 0.04
    ) -> dict:
        from scipy.optimize import minimize

        cov = returns.cov().values * 252
        n = len(symbols)

        def risk_budget_obj(w):
            port_vol = np.sqrt(w @ cov @ w)
            marginal_risk = (cov @ w) / port_vol
            risk_contrib = w * marginal_risk
            target = port_vol / n
            return float(cast(Any, np.sum((risk_contrib - target) ** 2)))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.01, MAX_SINGLE_WEIGHT)] * n
        w0 = np.ones(n) / n
        result = minimize(risk_budget_obj, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        opt_w = result.x if result.success else w0

        mu = returns.mean() * 252
        port_ret = float(cast(Any, opt_w) @ cast(Any, mu.values))
        port_vol = float(np.sqrt(cast(Any, opt_w) @ cast(Any, cov) @ cast(Any, opt_w)))

        return {
            "target_weights": {sym: round(float(cast(Any, w)), 4) for sym, w in zip(symbols, opt_w)},
            "current_weights": current_weights,
            "frontier_data": [],
            "expected_return": round(port_ret, 4),
            "expected_volatility": round(port_vol, 4),
            "sharpe_ratio": round((port_ret - rf) / port_vol, 4) if port_vol > 0 else 0.0,
            "method": "RISK_PARITY",
        }

    # ──────────────────────────────────────────
    # Kelly Criterion（半 Kelly，上限 25%）
    # ──────────────────────────────────────────

    def _kelly(
        self, returns: pd.DataFrame, symbols: List[str], current_weights: dict, rf: float = 0.04
    ) -> dict:
        mu = returns.mean() * 252
        cov = returns.cov() * 252
        try:
            inv_cov = np.linalg.inv(cov.values)
        except np.linalg.LinAlgError:
            inv_cov = np.linalg.pinv(cov.values)

        kelly_w = cast(Any, inv_cov) @ cast(Any, mu.values)
        kelly_w = np.clip(kelly_w, 0, None)
        if kelly_w.sum() > 0:
            kelly_w /= kelly_w.sum()

        # 半 Kelly + 单标的上限
        half_w = kelly_w * HALF_KELLY
        half_w = np.clip(half_w, 0, MAX_SINGLE_WEIGHT)
        half_w /= half_w.sum() if half_w.sum() > 0 else 1

        port_ret = float(cast(Any, half_w) @ cast(Any, mu.values))
        port_vol = float(np.sqrt(cast(Any, half_w) @ cast(Any, cov.values) @ cast(Any, half_w)))

        return {
            "target_weights": {sym: round(float(cast(Any, w)), 4) for sym, w in zip(symbols, half_w)},
            "current_weights": current_weights,
            "frontier_data": [],
            "expected_return": round(port_ret, 4),
            "expected_volatility": round(port_vol, 4),
            "sharpe_ratio": round((port_ret - rf) / port_vol, 4) if port_vol > 0 else 0.0,
            "method": "KELLY",
        }

    # ──────────────────────────────────────────
    # 数据拉取
    # ──────────────────────────────────────────

    async def _fetch_returns(self, symbols: List[str], start: date, end: date) -> pd.DataFrame:
        tasks = [data_hub.get_ohlcv(sym, start, end) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        close_dict = {}
        for sym, r in zip(symbols, results):
            if isinstance(r, BaseException):
                logger.warning(f"Portfolio optimizer: skip {sym}: {r}")
                continue
            # pd.DataFrame Access
            close_dict[sym] = cast(Any, r)["close"]

        if not close_dict:
            return pd.DataFrame()

        df = pd.DataFrame(close_dict).dropna()
        return df.pct_change().dropna()


# 全局单例
portfolio_optimizer = PortfolioOptimizer()
