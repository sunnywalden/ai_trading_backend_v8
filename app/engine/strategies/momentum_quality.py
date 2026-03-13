"""
动量+质量因子策略
"""
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

from app.engine.strategies.base_strategy import BaseStrategy
from app.providers.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MomentumQuality(BaseStrategy):
    """动量+质量因子策略。"""

    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not universe:
            universe = await self._get_default_universe()

        market_data = MarketDataProvider()
        momentum_lookback = int(self.get_param("momentum_lookback", 126) or 126)
        top_n = int(self.get_param("position_cap", 5) or 5)
        momentum_weight = float(self.get_param("momentum_weight", 0.6) or 0.6)
        quality_weight = float(self.get_param("quality_weight", 0.4) or 0.4)
        min_momentum_threshold = float(self.get_param("momentum_threshold", 0.05) or 0.05)

        candidates: List[Dict[str, Any]] = []
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=momentum_lookback + 40)

        for symbol in universe:
            try:
                prices = await market_data.get_historical_prices(symbol, start_date, end_date)
                if len(prices) < max(40, momentum_lookback // 2):
                    continue

                latest_close = float(prices[-1]["close"])
                anchor_close = float(prices[max(0, len(prices) - momentum_lookback)]["close"])
                if latest_close <= 0 or anchor_close <= 0:
                    continue

                momentum_return = (latest_close - anchor_close) / anchor_close
                if momentum_return < min_momentum_threshold:
                    continue

                try:
                    stats = await market_data.get_key_statistics(symbol)
                except Exception as exc:
                    logger.debug("MomentumQuality key statistics unavailable for %s: %s", symbol, exc)
                    stats = {}

                roe = stats.get("roe")
                debt_to_equity = stats.get("debt_to_equity")
                free_cash_flow = stats.get("free_cash_flow")

                quality_components = []
                if roe is not None:
                    quality_components.append(max(0.0, min(float(roe), 1.0)))
                if debt_to_equity is not None:
                    debt_value = float(debt_to_equity)
                    quality_components.append(max(0.0, min(1.0, 1.0 - debt_value / 200.0)))
                if free_cash_flow is not None:
                    quality_components.append(1.0 if float(free_cash_flow) > 0 else 0.2)
                quality_score = (
                    sum(quality_components) / len(quality_components)
                    if quality_components
                    else None
                )

                momentum_score = max(0.0, min(momentum_return / 0.35, 1.0))
                effective_momentum_weight = momentum_weight
                effective_quality_weight = quality_weight if quality_score is not None else 0.0
                total_weight = effective_momentum_weight + effective_quality_weight
                if total_weight <= 0:
                    total_weight = 1.0
                composite = (
                    momentum_score * effective_momentum_weight
                    + (quality_score or 0.0) * effective_quality_weight
                ) / total_weight
                risk_score = max(20, min(65, 60 - composite * 25))

                candidates.append(
                    {
                        "symbol": symbol,
                        "score": composite,
                        "momentum_return": momentum_return,
                        "quality_score": quality_score,
                        "current_price": latest_close,
                        "risk_score": risk_score,
                        "roe": roe,
                        "debt_to_equity": debt_to_equity,
                        "free_cash_flow": free_cash_flow,
                    }
                )
            except Exception:
                continue

        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = candidates[:top_n]
        if not selected:
            return []

        weight = round(1.0 / len(selected), 4)
        signals: List[Dict[str, Any]] = []
        for candidate in selected:
            strength = int(min(98, max(65, candidate["score"] * 100)))
            signals.append(
                {
                    "symbol": candidate["symbol"],
                    "direction": "BUY",
                    "strength": strength,
                    "weight": weight,
                    "risk_score": candidate["risk_score"],
                    "target_price": float(candidate["current_price"] * 1.12),
                    "stop_loss": float(candidate["current_price"] * 0.93),
                    "metadata": {
                        "strategy": "momentum_quality",
                        "entry_price": candidate["current_price"],
                        "momentum_return": candidate["momentum_return"],
                        "quality_score": candidate["quality_score"],
                        "roe": candidate["roe"],
                        "debt_to_equity": candidate["debt_to_equity"],
                        "free_cash_flow": candidate["free_cash_flow"],
                    },
                }
            )
        return signals

    async def _get_default_universe(self) -> List[str]:
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
            "META", "AVGO", "TSLA", "JPM", "V",
            "COST", "WMT", "LLY", "UNH", "PG",
        ]
