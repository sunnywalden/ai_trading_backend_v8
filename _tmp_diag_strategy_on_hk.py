import asyncio
from types import SimpleNamespace

from app.engine.strategies.breakout_momentum import BreakoutMomentum
from app.engine.strategies.momentum_quality import MomentumQuality

SYMBOLS = ["00700", "01528"]


async def main() -> None:
    dummy_session = SimpleNamespace(execute=None)

    mq = MomentumQuality(params={"position_cap": 5, "momentum_threshold": 0.03}, session=dummy_session)
    bo = BreakoutMomentum(params={"lookback_days": 20, "volume_multiplier": 1.1}, session=dummy_session)

    for strategy, name in [(mq, "momentum_quality"), (bo, "breakout_momentum")]:
        try:
            signals = await strategy.generate_signals(universe=SYMBOLS)
            print(name, signals)
        except Exception as exc:
            print(name, {"error": str(exc)})

if __name__ == "__main__":
    asyncio.run(main())
