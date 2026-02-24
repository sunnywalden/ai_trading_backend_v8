"""V10: RiskGateService — 非绕过风险门（在任何自主下单前必须通过）"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RiskGateResult:
    passed: bool
    reason: Optional[str] = None
    circuit_breaker: bool = False
    details: Optional[dict] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class RiskGateService:
    """
    非绕过风险检查：
    1. 单标的仓位占比  ≤ MAX_SINGLE_POSITION_PCT
    2. 投资组合 VaR@95% ≤ MAX_VAR_PCT
    3. 压力测试损失    ≤ MAX_STRESS_LOSS_PCT
    4. 当日已交易笔数  ≤ MAX_DAILY_TRADES
    5. 当日已实现亏损  → 触发 Circuit Breaker
    """

    async def check(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        side: str,
        current_equity: float,
        current_positions: dict,  # {symbol: {"qty": float, "price": float}}
        daily_trades_today: int = 0,
        daily_realized_pnl: float = 0.0,
    ) -> RiskGateResult:
        details = {}

        # ── 1. 熔断检查（最优先）──
        daily_loss_pct = abs(daily_realized_pnl) / current_equity if daily_realized_pnl < 0 else 0
        if daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            logger.warning(
                f"[RiskGate] Circuit breaker triggered. daily_loss={daily_loss_pct:.1%} >= {settings.MAX_DAILY_LOSS_PCT:.1%}"
            )
            return RiskGateResult(
                passed=False,
                reason=f"Circuit breaker: daily loss {daily_loss_pct:.1%} ≥ {settings.MAX_DAILY_LOSS_PCT:.1%}",
                circuit_breaker=True,
                details={"daily_loss_pct": daily_loss_pct},
            )

        # ── 2. 日交易笔数限制 ──
        if daily_trades_today >= settings.MAX_DAILY_TRADES:
            return RiskGateResult(
                passed=False,
                reason=f"Max daily trades reached: {daily_trades_today}/{settings.MAX_DAILY_TRADES}",
                details={"daily_trades": daily_trades_today},
            )

        # ── 3. 单标的仓位占比 ──
        if side == "BUY":
            # 预估下单后仓位市值
            existing_value = 0.0
            if symbol in current_positions:
                pos = current_positions[symbol]
                existing_value = pos.get("qty", 0) * pos.get("price", 0)
            new_value = qty * (current_positions.get(symbol, {}).get("price", 1.0))
            projected_pct = (existing_value + new_value) / current_equity if current_equity > 0 else 0
            details["projected_position_pct"] = round(projected_pct, 4)

            if projected_pct > settings.MAX_SINGLE_POSITION_PCT:
                return RiskGateResult(
                    passed=False,
                    reason=f"Position limit: {projected_pct:.1%} > {settings.MAX_SINGLE_POSITION_PCT:.1%}",
                    details=details,
                )

        # ── 4. VaR@95% 估算（简化：正态分布假设）──
        var_pct = self._estimate_var(current_positions, current_equity)
        details["estimated_var_pct"] = round(var_pct, 4)
        if var_pct > settings.MAX_VAR_PCT:
            return RiskGateResult(
                passed=False,
                reason=f"VaR limit: {var_pct:.1%} > {settings.MAX_VAR_PCT:.1%}",
                details=details,
            )

        # ── 5. 内置压力测试（GFC 场景 -50%，检查组合损失）──
        stress_loss_pct = self._estimate_stress_loss(current_positions, current_equity)
        details["stress_loss_pct"] = round(stress_loss_pct, 4)
        if stress_loss_pct > settings.MAX_STRESS_LOSS_PCT:
            return RiskGateResult(
                passed=False,
                reason=f"Stress test limit: {stress_loss_pct:.1%} > {settings.MAX_STRESS_LOSS_PCT:.1%}",
                details=details,
            )

        logger.info(f"[RiskGate] PASSED for {symbol} {side} qty={qty:.2f}. details={details}")
        return RiskGateResult(passed=True, details=details)

    # ──────────────────────────────────────────
    # 内部估算函数
    # ──────────────────────────────────────────

    def _estimate_var(self, positions: dict, equity: float, confidence: float = 0.95) -> float:
        """简化 VaR：假设持仓等权重，年化波动率 30%，正态分布单日 VaR"""
        if equity <= 0:
            return 0.0
        total_market_value = sum(
            pos.get("qty", 0) * pos.get("price", 0) for pos in positions.values()
        )
        exposure_pct = total_market_value / equity
        # 日波动率假设 30%/sqrt(252) ≈ 1.89%
        daily_vol = 0.30 / (252 ** 0.5)
        # 95% VaR ≈ 1.645 * daily_vol
        from scipy import stats as scipy_stats
        z = abs(scipy_stats.norm.ppf(1 - confidence))
        return exposure_pct * daily_vol * z

    def _estimate_stress_loss(self, positions: dict, equity: float) -> float:
        """GFC 情景：股票下跌 50%，计算组合损失占净值比"""
        if equity <= 0:
            return 0.0
        total_market_value = sum(
            pos.get("qty", 0) * pos.get("price", 0) for pos in positions.values()
        )
        stress_shock = 0.50  # GFC -50%
        return (total_market_value * stress_shock) / equity


# 全局单例
risk_gate_service = RiskGateService()
