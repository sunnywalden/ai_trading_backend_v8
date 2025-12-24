from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_mode import TradeMode
from app.services.policies import ShockPolicy, EarningsShockPolicy
from app.services.symbol_risk_profile_service import (
    SymbolRiskProfileService,
    SymbolBehaviorStatsDTO,
)


@dataclass
class EffectiveRiskLimits:
    max_order_notional_usd: float = 20000.0
    max_total_gamma_pct: float = 0.2
    max_total_vega_pct: float = 0.2
    max_total_theta_pct: float = 0.05


@dataclass
class EffectiveRiskState:
    effective_trade_mode: TradeMode
    limits: EffectiveRiskLimits
    global_shock_policy: ShockPolicy
    global_earnings_policy: EarningsShockPolicy
    symbol_shock_policies: Dict[str, ShockPolicy] = field(default_factory=dict)
    symbol_earnings_policies: Dict[str, EarningsShockPolicy] = field(default_factory=dict)
    symbol_behavior_tiers: Dict[str, str] = field(default_factory=dict)
    earnings_windows: Dict[str, Dict] = field(default_factory=dict)


class RiskConfigService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.profile_svc = SymbolRiskProfileService(session)

    async def _get_relevant_symbols(self, account_id: str) -> Iterable[str]:
        # Demo: fixed set
        return ["META", "TSLA", "1810.HK"]

    def _load_global_shock_policy(self) -> ShockPolicy:
        return ShockPolicy()

    def _load_global_earnings_policy(self) -> EarningsShockPolicy:
        return EarningsShockPolicy()

    async def get_effective_state(self, account_id: str) -> EffectiveRiskState:
        symbols = list(await self._get_relevant_symbols(account_id))
        profiles = await self.profile_svc.get_profiles(symbols)
        behaviors = await self.profile_svc.get_behavior_stats(account_id, symbols)

        base_shock = self._load_global_shock_policy()
        base_earn = self._load_global_earnings_policy()

        symbol_shock_policies: Dict[str, ShockPolicy] = {}
        symbol_earnings_policies: Dict[str, EarningsShockPolicy] = {}
        symbol_behavior_tiers: Dict[str, str] = {}
        earnings_windows: Dict[str, Dict] = {}

        for sym in symbols:
            prof = profiles.get(sym)
            stats = behaviors.get(sym)
            # 使用 profile 中的 shock_policy 和 earnings_policy，如果没有则使用默认
            sp = prof.shock_policy if prof else base_shock
            ep = prof.earnings_policy if prof else base_earn

            tier = self._behavior_tier(stats)
            sp_adj = self._adjust_shock_by_behavior(sp, stats, tier)
            ep_adj = self._adjust_earnings_by_behavior(ep, stats, tier)

            symbol_shock_policies[sym] = sp_adj
            symbol_earnings_policies[sym] = ep_adj
            symbol_behavior_tiers[sym] = tier
            earnings_windows[sym] = {"in_window": False}  # demo

        limits = EffectiveRiskLimits()
        return EffectiveRiskState(
            effective_trade_mode=TradeMode.DRY_RUN,
            limits=limits,
            global_shock_policy=base_shock,
            global_earnings_policy=base_earn,
            symbol_shock_policies=symbol_shock_policies,
            symbol_earnings_policies=symbol_earnings_policies,
            symbol_behavior_tiers=symbol_behavior_tiers,
            earnings_windows=earnings_windows,
        )

    def _behavior_tier(self, stats: Optional[SymbolBehaviorStatsDTO]) -> str:
        if not stats:
            return "T2"
        if stats.behavior_score >= 80 and stats.sell_fly_score <= 30:
            return "T1"
        if stats.behavior_score < 30 or stats.sell_fly_score >= 80:
            return "T4"
        if stats.behavior_score < 50 or stats.sell_fly_score >= 50:
            return "T3"
        return "T2"

    def _adjust_shock_by_behavior(self, base: ShockPolicy, stats: Optional[SymbolBehaviorStatsDTO], tier: str) -> ShockPolicy:
        alert_factor = 1.0
        emer_reduce_factor = 1.0
        emer_new_risk_factor = 1.0

        if tier == "T1":
            alert_factor = 1.1
            emer_reduce_factor = 0.9
            emer_new_risk_factor = 1.1
        elif tier == "T3":
            alert_factor = 0.9
            emer_reduce_factor = 1.2
            emer_new_risk_factor = 0.8
        elif tier == "T4":
            alert_factor = 0.8
            emer_reduce_factor = 1.5
            emer_new_risk_factor = 0.6

        return ShockPolicy(
            alert_drop_pct=base.alert_drop_pct * alert_factor,
            alert_rally_pct=base.alert_rally_pct * alert_factor,
            emergency_drop_pct=base.emergency_drop_pct * alert_factor,
            emergency_rally_pct=base.emergency_rally_pct * alert_factor,
            intrabar_shock_pct=base.intrabar_shock_pct * alert_factor,
            window_minutes=base.window_minutes,
            emergency_reduce_fraction=min(1.0, base.emergency_reduce_fraction * emer_reduce_factor),
            emergency_max_new_risk_factor=base.emergency_max_new_risk_factor * emer_new_risk_factor,
            recovery_minutes=base.recovery_minutes,
            recovery_risk_factor=base.recovery_risk_factor,
        )

    def _adjust_earnings_by_behavior(self, base: EarningsShockPolicy, stats: Optional[SymbolBehaviorStatsDTO], tier: str) -> EarningsShockPolicy:
        vega_factor = base.vega_factor
        gamma_factor = base.gamma_factor
        theta_factor = base.theta_factor
        short_dte_factor = base.short_dte_factor

        min_dte_long = base.min_dte_for_new_long
        min_dte_short = base.min_dte_for_new_short

        if tier == "T3":
            vega_factor *= 0.8
            gamma_factor *= 0.8
            short_dte_factor *= 0.7
            min_dte_short += 5
        elif tier == "T4":
            vega_factor *= 0.6
            gamma_factor *= 0.6
            theta_factor *= 0.8
            short_dte_factor *= 0.5
            min_dte_long += 3
            min_dte_short += 10

        return EarningsShockPolicy(
            pre_days=base.pre_days,
            post_days=base.post_days,
            vega_factor=vega_factor,
            gamma_factor=gamma_factor,
            theta_factor=theta_factor,
            short_dte_factor=short_dte_factor,
            forbid_new_naked_shorts=base.forbid_new_naked_shorts,
            require_spreads_for_shorts=base.require_spreads_for_shorts,
            min_dte_for_new_long=min_dte_long,
            min_dte_for_new_short=min_dte_short,
        )

    async def apply_shock_risk_factor(self, account_id: str, factor: float, scope: str, reason: str):
        print(f"[RiskConfig] apply_shock_risk_factor account={account_id} factor={factor} scope={scope} reason={reason}")

    async def apply_emergency_mode(self, account_id: str, symbol: str, policy: ShockPolicy):
        print(f"[RiskConfig] EMERGENCY mode for {account_id} {symbol}")
