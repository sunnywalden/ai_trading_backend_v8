"""
动量+质量因子策略
"""
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

from app.engine.strategies.base_strategy import BaseStrategy
from app.providers.market_data_provider import market_data_provider
from app.services.non_realtime_data_policy import NonRealtimeDataPolicyService

logger = logging.getLogger(__name__)


class MomentumQuality(BaseStrategy):
    """动量+质量因子策略。"""

    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not universe:
            universe = await self._get_default_universe()

        market_data = market_data_provider
        data_policy = NonRealtimeDataPolicyService.runtime_signal_generation()
        momentum_lookback = int(self.get_param("momentum_lookback", 126) or 126)
        top_n = int(self.get_param("position_cap", 5) or 5)
        momentum_weight = float(self.get_param("momentum_weight", 0.6) or 0.6)
        quality_weight = float(self.get_param("quality_weight", 0.4) or 0.4)
        long_momentum_threshold = float(self.get_param("momentum_threshold", 0.05) or 0.05)
        short_momentum_threshold = float(self.get_param("short_momentum_threshold", 0.05) or 0.05)
        fallback_momentum_floor = float(self.get_param("fallback_momentum_floor", -0.03) or -0.03)

        candidates: List[Dict[str, Any]] = []
        fallback_candidates: List[Dict[str, Any]] = []
        end_date = datetime.now(UTC).replace(tzinfo=None)
        start_date = end_date - timedelta(days=momentum_lookback + 40)

        for symbol in universe:
            try:
                prices = await market_data.get_historical_prices(
                    symbol,
                    start_date,
                    end_date,
                    cache_only=data_policy.historical_cache_only,
                )
                if len(prices) < max(40, momentum_lookback // 2):
                    continue

                latest_close = float(prices[-1]["close"])
                anchor_close = float(prices[max(0, len(prices) - momentum_lookback)]["close"])
                if latest_close <= 0 or anchor_close <= 0:
                    continue

                momentum_return = (latest_close - anchor_close) / anchor_close

                try:
                    stats = await market_data.get_key_statistics(
                        symbol,
                        cache_only=data_policy.key_statistics_cache_only,
                    )
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

                momentum_score = max(0.0, min(abs(momentum_return) / 0.35, 1.0))
                effective_momentum_weight = momentum_weight
                effective_quality_weight = quality_weight if quality_score is not None else 0.0
                total_weight = effective_momentum_weight + effective_quality_weight
                if total_weight <= 0:
                    total_weight = 1.0
                is_short_bias = momentum_return < 0
                quality_component = quality_score or 0.0
                if is_short_bias and quality_score is not None:
                    quality_component = max(0.0, min(1.0, 1.0 - quality_score))
                composite = (
                    momentum_score * effective_momentum_weight
                    + quality_component * effective_quality_weight
                ) / total_weight
                risk_score = max(20, min(65, 60 - composite * 25))
                direction = "SELL" if is_short_bias else "BUY"

                candidate = {
                    "symbol": symbol,
                    "score": composite,
                    "direction": direction,
                    "momentum_return": momentum_return,
                    "quality_score": quality_score,
                    "current_price": latest_close,
                    "risk_score": risk_score,
                    "roe": roe,
                    "debt_to_equity": debt_to_equity,
                    "free_cash_flow": free_cash_flow,
                    "used_ranked_fallback": False,
                }

                if momentum_return >= long_momentum_threshold or momentum_return <= -short_momentum_threshold:
                    candidates.append(candidate)
                elif momentum_return >= fallback_momentum_floor:
                    fallback_candidates.append(candidate)
            except Exception:
                continue

        source_candidates = candidates
        if not source_candidates and fallback_candidates:
            fallback_candidates.sort(key=lambda item: item["score"], reverse=True)
            for candidate in fallback_candidates:
                candidate["used_ranked_fallback"] = True
            source_candidates = fallback_candidates

        source_candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = source_candidates[:top_n]
        if not selected:
            return []

        weight = round(1.0 / len(selected), 4)
        signals: List[Dict[str, Any]] = []
        for candidate in selected:
            strength = int(min(98, max(65, candidate["score"] * 100)))
            signals.append(
                {
                    "symbol": candidate["symbol"],
                    "direction": candidate["direction"],
                    "strength": strength,
                    "weight": weight,
                    "risk_score": candidate["risk_score"],
                    "target_price": float(
                        candidate["current_price"] * (0.88 if candidate["direction"] == "SELL" else 1.12)
                    ),
                    "stop_loss": float(
                        candidate["current_price"] * (1.07 if candidate["direction"] == "SELL" else 0.93)
                    ),
                    "metadata": {
                        "strategy": "momentum_quality",
                        "entry_price": candidate["current_price"],
                        "position_bias": "SHORT" if candidate["direction"] == "SELL" else "LONG",
                        "momentum_return": candidate["momentum_return"],
                        "quality_score": candidate["quality_score"],
                        "roe": candidate["roe"],
                        "debt_to_equity": candidate["debt_to_equity"],
                        "free_cash_flow": candidate["free_cash_flow"],
                        "used_ranked_fallback": candidate["used_ranked_fallback"],
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
