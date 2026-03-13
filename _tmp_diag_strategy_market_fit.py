from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from app.engine.strategies.bollinger_bands import BollingerBandsMeanReversion
from app.engine.strategies.breakout_momentum import BreakoutMomentum
from app.engine.strategies.golden_cross import GoldenCross
from app.engine.strategies.low_volatility import LowVolatility
from app.engine.strategies.momentum_quality import MomentumQuality
from app.models.db import SessionLocal
from app.models.strategy import Strategy

HK_SYMBOLS = ["00700", "09988", "03690", "01810", "09618", "09888", "00005", "02318", "01299", "00941", "01528", "02192"]
US_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "ORCL", "QCOM", "SPY"]

IMPLS = {
    "bollinger_mean_reversion": BollingerBandsMeanReversion,
    "breakout_momentum": BreakoutMomentum,
    "golden_cross": GoldenCross,
    "momentum_quality": MomentumQuality,
    "low_volatility": LowVolatility,
}

ALIASES = {
    "事件驱动": "breakout_momentum",
    "突破": "breakout_momentum",
    "黄金": "golden_cross",
    "量化": "momentum_quality",
    "轮动": "momentum_quality",
    "布林": "bollinger_mean_reversion",
    "低波": "low_volatility",
}


def resolve_impl(strategy: Strategy) -> str | None:
    candidates = [str(getattr(strategy, 'id', '') or ''), str(strategy.name or ''), str(strategy.style or '')]
    for key in IMPLS:
        if key in candidates:
            return key
    text = ' '.join(candidates)
    for hint, key in ALIASES.items():
        if hint in text:
            return key
    return None


async def run_market(session, market_name: str, symbols: list[str]) -> None:
    print(f"\n=== {market_name} ===")
    stmt = select(Strategy).where(Strategy.is_active.is_(True), Strategy.auto_scan_enabled.is_(True)).order_by(Strategy.auto_scan_priority.desc())
    strategies = (await session.execute(stmt)).scalars().all()
    for strategy in strategies:
        impl_key = resolve_impl(strategy)
        if not impl_key:
            continue
        impl_cls = IMPLS.get(impl_key)
        if not impl_cls:
            continue
        try:
            impl = impl_cls(params=(strategy.default_params or {}), session=session)
            signals = await impl.generate_signals(universe=symbols)
            print({
                "strategy": strategy.name,
                "impl": impl_key,
                "market": market_name,
                "signal_count": len(signals),
                "symbols": [s.get('symbol') for s in signals[:5]],
            })
        except Exception as exc:
            print({
                "strategy": strategy.name,
                "impl": impl_key,
                "market": market_name,
                "error": str(exc),
            })


async def main() -> None:
    async with SessionLocal() as session:
        await run_market(session, "HK", HK_SYMBOLS)
        await run_market(session, "US", US_SYMBOLS)


if __name__ == "__main__":
    asyncio.run(main())
