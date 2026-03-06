"""V10: RiskGateService — 非绕过风险门（在任何自主下单前必须通过）

V10.2-M1 升级：支持体制感知 VaR 门限动态调整，通过 set_regime_var_multiplier() 注入体制倍数。
"""
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
    2. 投资组合 VaR@95% ≤ MAX_VAR_PCT × regime_multiplier  ★ V10.2: 体制感知倒数
    3. 压力测试损失    ≤ MAX_STRESS_LOSS_PCT
    4. 当日已交易笔数  ≤ MAX_DAILY_TRADES
    5. 当日已实现亏损  → 触发 Circuit Breaker
    """

    def __init__(self) -> None:
        # V10.2-M1: 体制感知 VaR 倍数，默认 1.0（不优化）
        # 由 StrategyWeightAllocator.on_regime_changed 当体制切换时更新
        self._regime_var_multiplier: float = 1.0
        self._current_regime: str = "UNKNOWN"

    @staticmethod
    def _is_closing_intent(signal_intent: Optional[str]) -> bool:
        intent = str(signal_intent or "OPEN").upper()
        return intent in {"REDUCE", "EXIT", "STOP_LOSS_EXIT", "TAKE_PROFIT_EXIT", "FORCE_EXIT"}

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
        signal_intent: str = "OPEN",
    ) -> RiskGateResult:
        details = {}
        is_closing = self._is_closing_intent(signal_intent)
        details["signal_intent"] = str(signal_intent or "OPEN").upper()
        details["is_closing_intent"] = is_closing

        # ── 1. 熔断检查（最优先）──
        daily_loss_pct = abs(daily_realized_pnl) / current_equity if daily_realized_pnl < 0 else 0
        if daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            if is_closing and getattr(settings, "ALLOW_CLOSING_DURING_CIRCUIT_BREAKER", True):
                details.update(
                    {
                        "daily_loss_pct": daily_loss_pct,
                        "bypass_reason": "closing_intent",
                        "circuit_breaker_active": True,
                    }
                )
                logger.warning(
                    "[RiskGate] Circuit breaker active but allowing risk-reducing order: "
                    f"{symbol} intent={signal_intent} daily_loss={daily_loss_pct:.1%}"
                )
                return RiskGateResult(
                    passed=True,
                    reason="circuit-breaker-active-but-closing-allowed",
                    circuit_breaker=True,
                    details=details,
                )
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
        if not is_closing and daily_trades_today >= settings.MAX_DAILY_TRADES:
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
        if not is_closing:
            var_pct = self._estimate_var(current_positions, current_equity)
            details["estimated_var_pct"] = round(var_pct, 4)
            # V10.2-M1: 应用体制感知 VaR 倍数
            effective_var_limit = settings.MAX_VAR_PCT * self._regime_var_multiplier
            details["regime_var_multiplier"] = self._regime_var_multiplier
            details["effective_var_limit"] = round(effective_var_limit, 4)
            if var_pct > effective_var_limit:
                return RiskGateResult(
                    passed=False,
                    reason=f"VaR limit: {var_pct:.1%} > {effective_var_limit:.1%} (regime={self._current_regime}, ×{self._regime_var_multiplier:.2f})",
                    details=details,
                )
        else:
            details["var_check_skipped"] = True

        # ── 5. 内置压力测试（GFC 场景 -50%，检查组合损失）──
        if not is_closing:
            stress_loss_pct = self._estimate_stress_loss(current_positions, current_equity)
            details["stress_loss_pct"] = round(stress_loss_pct, 4)
            if stress_loss_pct > settings.MAX_STRESS_LOSS_PCT:
                return RiskGateResult(
                    passed=False,
                    reason=f"Stress test limit: {stress_loss_pct:.1%} > {settings.MAX_STRESS_LOSS_PCT:.1%}",
                    details=details,
                )
        else:
            details["stress_check_skipped"] = True

        logger.info(f"[RiskGate] PASSED for {symbol} {side} qty={qty:.2f}. details={details}")
        return RiskGateResult(passed=True, details=details)

    # ──────────────────────────────────────────
    # V10.2-M1: 体制感知 VaR 倍数切换
    # ──────────────────────────────────────────

    def set_regime_var_multiplier(self, regime: str) -> None:
        """
        体制切换时由 StrategyWeightAllocator 调用。

        从 settings.REGIME_VAR_MULTIPLIERS 读取对应体制的 VaR 倍数，
        并实时更新 self._regime_var_multiplier。

        Parameters
        ----------
        regime : str  如 "BULL_TREND"
        """
        multipliers: dict[str, float] = {}
        try:
            for item in settings.REGIME_VAR_MULTIPLIERS.split(","):
                item = item.strip()
                if ":" in item:
                    r, m = item.split(":", 1)
                    multipliers[r.strip()] = float(m.strip())
        except Exception as exc:
            logger.warning(f"[RiskGate] Failed to parse REGIME_VAR_MULTIPLIERS: {exc}")

        new_multiplier = multipliers.get(regime.upper(), 1.0)
        old_multiplier = self._regime_var_multiplier
        self._regime_var_multiplier = new_multiplier
        self._current_regime = regime
        logger.info(
            f"[RiskGate] VaR multiplier updated: ×{old_multiplier:.2f} → ×{new_multiplier:.2f} "
            f"(regime={regime}, effective_var_limit={settings.MAX_VAR_PCT * new_multiplier:.2%})"
        )

    def get_regime_var_multiplier(self) -> float:
        """  返回当前体制 VaR 倍数（供审计日志和给 Router 查询用）。"""
        return self._regime_var_multiplier

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
