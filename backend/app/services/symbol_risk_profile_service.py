from typing import Dict, Iterable, Optional
from dataclasses import dataclass, asdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.symbol_risk_profile import SymbolRiskProfile
from app.models.symbol_behavior_stats import SymbolBehaviorStats
from app.services.policies import ShockPolicy, EarningsShockPolicy


@dataclass
class SymbolRiskProfileDTO:
    symbol: str
    market: str
    vol_level: str
    liquidity_level: str
    shock_policy: ShockPolicy
    earnings_policy: EarningsShockPolicy


@dataclass
class SymbolBehaviorStatsDTO:
    symbol: str
    behavior_score: int
    sell_fly_score: int
    overtrade_score: int
    revenge_trade_score: int

    trade_count: int = 0
    sell_fly_events: int = 0
    sell_fly_extra_cost_ratio: float = 0.0
    overtrade_index: float = 0.0
    revenge_events: int = 0


class SymbolRiskProfileService:
    """提供 symbol 风险画像（静态配置）和行为统计画像（动态行为评分）。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # -------- 静态风险画像（来自 symbol_risk_profile 表） --------

    async def get_profiles(
        self,
        symbols: Iterable[str],
        default_market: str = "US",
    ) -> Dict[str, SymbolRiskProfileDTO]:
        """返回指定 symbols 的风险画像配置。

        若某 symbol 没有单独配置，则返回默认画像（中等波动、高流动性、默认 Shock/Earnings 策略）。
        """
        symbol_list = list(set(symbols))
        if not symbol_list:
            return {}

        stmt = select(SymbolRiskProfile).where(
            and_(
                SymbolRiskProfile.symbol.in_(symbol_list),
                SymbolRiskProfile.enabled.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        profiles: Dict[str, SymbolRiskProfileDTO] = {}
        for row in rows:
            shock = self._decode_shock(row.shock_policy_json) if row.use_custom_shock else ShockPolicy()
            earnings = self._decode_earnings(row.earnings_policy_json) if row.use_custom_earnings else EarningsShockPolicy()
            profiles[row.symbol] = SymbolRiskProfileDTO(
                symbol=row.symbol,
                market=row.market or default_market,
                vol_level=row.vol_level or "MEDIUM",
                liquidity_level=row.liquidity_level or "HIGH",
                shock_policy=shock,
                earnings_policy=earnings,
            )

        # 对于未配置的 symbol，用默认画像补齐
        for sym in symbol_list:
            if sym in profiles:
                continue
            profiles[sym] = SymbolRiskProfileDTO(
                symbol=sym,
                market=default_market,
                vol_level="MEDIUM",
                liquidity_level="HIGH",
                shock_policy=ShockPolicy(),
                earnings_policy=EarningsShockPolicy(),
            )

        return profiles

    def _decode_shock(self, data: Optional[dict]) -> ShockPolicy:
        if not data:
            return ShockPolicy()
        return ShockPolicy(**{**asdict(ShockPolicy()), **data})

    def _decode_earnings(self, data: Optional[dict]) -> EarningsShockPolicy:
        if not data:
            return EarningsShockPolicy()
        return EarningsShockPolicy(**{**asdict(EarningsShockPolicy()), **data})

    # -------- 行为统计画像（来自 symbol_behavior_stats 表） --------

    async def get_behavior_stats(
        self,
        account_id: str,
        symbols: Iterable[str],
        window_days: int = 60,
    ) -> Dict[str, SymbolBehaviorStatsDTO]:
        """返回行为统计画像（用于风控动态限额和前端展示）。

        - behavior_score: 综合行为评分
        - sell_fly_score: 卖飞维度评分
        - overtrade_score: 过度交易评分
        - revenge_trade_score: 报复性交易评分
        - trade_count / sell_fly_events / overtrade_index / revenge_events: 原始指标
        """
        symbol_list = list(set(symbols))
        if not symbol_list:
            return {}

        print(f"[get_behavior_stats] Querying with account_id={account_id}, symbols={symbol_list}, window_days={window_days}")
        
        stmt = select(SymbolBehaviorStats).where(
            and_(
                SymbolBehaviorStats.account_id == account_id,
                SymbolBehaviorStats.symbol.in_(symbol_list),
                SymbolBehaviorStats.window_days == window_days,
            )
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        
        print(f"[get_behavior_stats] Found {len(rows)} rows in database")

        stats_map: Dict[str, SymbolBehaviorStatsDTO] = {}
        for row in rows:
            stats_map[row.symbol] = SymbolBehaviorStatsDTO(
                symbol=row.symbol,
                behavior_score=row.behavior_score,
                sell_fly_score=row.sell_fly_score,
                overtrade_score=row.overtrade_score,
                revenge_trade_score=row.revenge_trade_score,
                trade_count=row.trade_count or 0,
                sell_fly_events=getattr(row, "sell_fly_events", 0) or 0,
                sell_fly_extra_cost_ratio=float(getattr(row, "sell_fly_extra_cost_ratio", 0) or 0),
                overtrade_index=float(getattr(row, "overtrade_index", 0) or 0),
                revenge_events=getattr(row, "revenge_events", 0) or 0,
            )

        return stats_map
