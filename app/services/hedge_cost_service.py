from dataclasses import dataclass
from typing import List, Dict

from app.services.option_exposure_service import AccountOptionExposure, OptionExposureService


@dataclass
class HedgeCandidate:
    symbol: str
    instrument: str
    actions: List[Dict]
    label: str
    comment: str


@dataclass
class HedgeCostResult:
    candidate: HedgeCandidate
    risk_before: float
    risk_after: float
    delta_risk_reduction: float
    cash_cost: float
    friction_cost: float
    theta_cost: float
    liquidity_cost: float
    total_cost: float
    score: float


class HedgeCostService:
    def __init__(self, session):
        self.session = session
        self.expo_svc = OptionExposureService(session)
        self.w_delta = 1.0
        self.w_gamma = 1.5
        self.w_vega = 1.2
        self.w_theta = 0.8

    def _risk_score(self, exp: AccountOptionExposure) -> float:
        eq = exp.equity_usd or 1.0
        delta_pct = exp.total_delta_notional_usd / eq
        gamma_pct = exp.total_gamma_usd / eq
        vega_pct = exp.total_vega_usd / eq
        theta_pct = exp.total_theta_usd / eq

        short_gamma_pct = exp.short_dte_gamma_usd / eq
        short_theta_pct = exp.short_dte_theta_usd / eq

        gamma_effective = abs(gamma_pct) + 0.5 * abs(short_gamma_pct)
        theta_effective = abs(theta_pct) + 0.5 * abs(short_theta_pct)

        return (
            self.w_delta * abs(delta_pct)
            + self.w_gamma * gamma_effective
            + self.w_vega * abs(vega_pct)
            + self.w_theta * theta_effective
        )

    async def estimate_costs_for_candidate(self, base_exp: AccountOptionExposure, candidate: HedgeCandidate) -> HedgeCostResult:
        R_before = self._risk_score(base_exp)
        exp_after = await self.expo_svc.simulate_apply_actions(base_exp, candidate.actions)
        R_after = self._risk_score(exp_after)
        delta_R = max(0.0, R_before - R_after)

        cash_cost = 0.0
        friction_cost = 0.0
        theta_cost = 0.0
        liquidity_cost = 0.0

        for act in candidate.actions:
            instr = act.get("instrument")
            qty = abs(act.get("quantity", 0))
            if instr == "STOCK":
                cash_cost += 10 * qty
            elif instr == "OPTION":
                cash_cost += 5 * qty
                theta_cost += 1 * qty

        total_cost = cash_cost + friction_cost + theta_cost + liquidity_cost
        eps = 1e-6
        score = total_cost / (delta_R + eps) if delta_R > 0 else float("inf")

        return HedgeCostResult(
            candidate=candidate,
            risk_before=R_before,
            risk_after=R_after,
            delta_risk_reduction=delta_R,
            cash_cost=cash_cost,
            friction_cost=friction_cost,
            theta_cost=theta_cost,
            liquidity_cost=liquidity_cost,
            total_cost=total_cost,
            score=score,
        )
