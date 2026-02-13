from typing import List

from app.services.hedge_cost_service import HedgeCandidate, HedgeCostService, HedgeCostResult
from app.services.option_exposure_service import OptionExposureService
from app.services.risk_config_service import RiskConfigService


class HedgeAdvisorService:
    def __init__(self, session):
        self.session = session
        self.expo = OptionExposureService(session)
        self.risk = RiskConfigService(session)

    async def generate_best_for_risk(self, account_id: str) -> List[HedgeCostResult]:
        base_exp = await self.expo.get_account_exposure(account_id)
        await self.risk.get_effective_state(account_id)  # not used further in demo

        candidates: List[HedgeCandidate] = []

        candidates.append(
            HedgeCandidate(
                symbol=base_exp.main_symbol,
                instrument="STOCK",
                label="stock_delta_hedge",
                comment="减持现货对冲 Delta",
                actions=[{
                    "instrument": "STOCK",
                    "symbol": base_exp.main_symbol,
                    "side": "SELL",
                    "quantity": 10,
                }],
            )
        )

        candidates.append(
            HedgeCandidate(
                symbol=base_exp.main_symbol,
                instrument="OPTION",
                label="option_gamma_hedge",
                comment="买入期权对冲 Gamma/Vega",
                actions=[{
                    "instrument": "OPTION",
                    "symbol": base_exp.main_symbol,
                    "side": "BUY",
                    "quantity": 1,
                    "dte": 30,
                    "moneyness": "ATM",
                }],
            )
        )

        cost_svc = HedgeCostService(self.session)
        results: List[HedgeCostResult] = []
        for c in candidates:
            res = await cost_svc.estimate_costs_for_candidate(base_exp, c)
            if res.delta_risk_reduction > 0:
                results.append(res)

        results.sort(key=lambda r: r.score)
        return results[:3]
