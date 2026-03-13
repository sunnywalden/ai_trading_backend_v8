from dataclasses import dataclass
from typing import Dict

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.trade_mode import TradeMode
from app.core.order_intent import OrderIntent
from app.services.risk_config_service import RiskConfigService
from app.services.hedge_advisor_service import HedgeAdvisorService
from app.services.account_service import AccountService
from app.services.option_exposure_service import OptionExposureService
from app.services.safety_guard import SafetyGuard
from app.services.risk_event_logger import log_risk_event
from app.broker.factory import make_option_broker_client

logger = logging.getLogger(__name__)


@dataclass
class HedgeOrderPlan:
    symbol: str
    instrument: str
    side: str
    quantity: int
    reason: str
    meta: Dict


class AutoHedgeEngine:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.risk_svc = RiskConfigService(session)
        self.hedge_svc = HedgeAdvisorService(session)
        self.account_svc = AccountService(session)
        # 使用工厂方法选择 Tiger 或 Dummy 客户端
        broker_client = make_option_broker_client()
        self.broker = broker_client
        self.expo_svc = OptionExposureService(session, broker_client)

    async def run_once(self) -> None:
        account_id = settings.TIGER_ACCOUNT
        eff_state = await self.risk_svc.get_effective_state(account_id)
        if eff_state.effective_trade_mode == TradeMode.OFF:
            return

        results = await self.hedge_svc.generate_best_for_risk(account_id)
        if not results:
            return

        best = results[0]
        first_action = best.candidate.actions[0]
        plan = HedgeOrderPlan(
            symbol=best.candidate.symbol,
            instrument=best.candidate.instrument,
            side=first_action.get("side", "SELL"),
            quantity=first_action.get("quantity", 0),
            reason=f"[AUTO-HEDGE {best.candidate.label}] dR={best.delta_risk_reduction:.4f} cost={best.total_cost:.2f} score={best.score:.2f}",
            meta=first_action,
        )

        await self._execute_plan(account_id, eff_state, plan)

    async def _execute_plan(self, account_id: str, eff_state, plan: HedgeOrderPlan):
        eq = await self.account_svc.get_equity_usd(account_id)
        notional = 100 * abs(plan.quantity)

        guard = SafetyGuard(account_id, eff_state.limits, self.session)
        check = await guard.check_order(plan.side, notional)
        if not check.allowed:
            await log_risk_event(
                self.session,
                account_id=account_id,
                event_type="HEDGE_BLOCKED",
                level="BLOCK",
                message=check.reason or "",
                symbol=plan.symbol,
                trade_mode_before=str(eff_state.effective_trade_mode),
                trade_mode_after=str(eff_state.effective_trade_mode),
                extra_json={"plan": plan.meta},
            )
            return

        if eff_state.effective_trade_mode == TradeMode.DRY_RUN:
            await log_risk_event(
                self.session,
                account_id=account_id,
                event_type="HEDGE_SIMULATED",
                level="INFO",
                message=f"Simulated hedge: {plan.reason}",
                symbol=plan.symbol,
                trade_mode_before=str(eff_state.effective_trade_mode),
                trade_mode_after=str(eff_state.effective_trade_mode),
                extra_json={"plan": plan.meta, "notional": notional},
            )
            return

        order_params = {
            "symbol": plan.symbol,
            "direction": "LONG" if str(plan.side).upper() == "BUY" else "SHORT",
            "quantity": int(plan.quantity),
            "price": None,
            "order_type": "MARKET",
            "time_in_force": "DAY",
        }
        if plan.instrument != "STOCK":
            order_params.update({
                "asset_type": "OPTION",
                "option_meta": plan.meta,
            })

        resp = await self.broker.place_order(account_id, order_params)
        if not resp.get("success"):
            raise RuntimeError(f"Auto hedge broker order failed: {resp.get('message') or 'unknown error'}")

        logger.info(
            "[AutoHedge] Submitted real hedge order symbol=%s instrument=%s qty=%s order_id=%s",
            plan.symbol,
            plan.instrument,
            plan.quantity,
            resp.get("order_id"),
        )

        if plan.instrument == "STOCK":
            pass
        else:
            pass
