from dataclasses import dataclass

from app.services.option_exposure_service import AccountOptionExposure
from app.services.risk_config_service import EffectiveRiskLimits, EffectiveRiskState


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str | None = None


class SafetyGuard:
    def __init__(self, account_id: str, limits: EffectiveRiskLimits, session):
        self.account_id = account_id
        self.limits = limits
        self.session = session

    async def check_order(self, side: str, notional_usd: float, est_daily_pnl_pct=None) -> SafetyCheckResult:
        if notional_usd > self.limits.max_order_notional_usd:
            return SafetyCheckResult(False, f"订单名义金额超限: {notional_usd:.2f} > {self.limits.max_order_notional_usd:.2f}")
        return SafetyCheckResult(True)

    async def check_greeks_exposure(self, exposure: AccountOptionExposure, eff_state: EffectiveRiskState) -> SafetyCheckResult:
        eq = exposure.equity_usd or 1.0
        gamma_pct = exposure.total_gamma_usd / eq
        vega_pct = exposure.total_vega_usd / eq

        if abs(gamma_pct) > eff_state.limits.max_total_gamma_pct:
            return SafetyCheckResult(False, f"Gamma 暴露超限: {gamma_pct:.3f}")
        if abs(vega_pct) > eff_state.limits.max_total_vega_pct:
            return SafetyCheckResult(False, f"Vega 暴露超限: {vega_pct:.3f}")
        return SafetyCheckResult(True)

    async def check_theta_exposure(self, exposure: AccountOptionExposure, eff_state: EffectiveRiskState) -> SafetyCheckResult:
        eq = exposure.equity_usd or 1.0
        theta_pct = exposure.total_theta_usd / eq
        if abs(theta_pct) > eff_state.limits.max_total_theta_pct:
            return SafetyCheckResult(False, f"Theta 暴露超限: {theta_pct:.3f}")
        return SafetyCheckResult(True)
