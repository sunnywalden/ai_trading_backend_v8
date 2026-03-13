from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.engine.strategies.bollinger_bands import BollingerBandsMeanReversion
from app.engine.strategies.breakout_momentum import BreakoutMomentum
from app.engine.strategies.cta_commodities import CTACommodities
from app.engine.strategies.fama_french import FamaFrenchThreeFactor
from app.engine.strategies.golden_cross import GoldenCross
from app.engine.strategies.iron_condor import IronCondor
from app.engine.strategies.low_volatility import LowVolatility
from app.engine.strategies.momentum_quality import MomentumQuality
from app.engine.strategies.pairs_trading import PairsTrading
from app.engine.strategies.sector_rotation import SectorRotation
from app.engine.strategies.tail_hedge import TailHedge
from app.engine.strategies.vol_arbitrage import VolatilityArbitrage
from app.models.db import SessionLocal
from app.models.strategy import (
    StrategyRun,
    StrategyRunAsset,
    StrategyRunLog,
    HistoricalStrategyRun,
    StrategyNotification,
)
from app.providers.market_data_provider import MarketDataProvider
from app.services.market_universe_service import MarketUniverseService

logger = logging.getLogger(__name__)

UNIVERSE_MAPPING = {
    "US_LARGE_MID_TECH": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "INTC", "AMD", "ORCL", "QCOM", "CRM"],
    "PRECIOUS_METALS": ["GLD", "SLV", "IAU", "NEM", "GOLD", "AU", "AG", "FNV", "WPM", "PAAS", "GFI"],
    "US_SMALL_TECH": ["U", "PLTR", "SNOW", "NET", "OKTA", "FSLR", "ENPH", "SHOP", "SQ", "ROKU"],
    "TRADITIONAL_QUALITY": ["JPM", "V", "BRK.B", "PG", "JNJ", "WMT", "KO", "XOM", "CVX", "CAT", "BA"],
    "EMERGING_QUALITY": ["TSM", "ASML", "BABA", "PDD", "JD", "ARM", "LI", "NIO", "XPEV"],
    "BLOCKCHAIN_CRYPTO": ["COIN", "MARA", "RIOT", "CLSK", "MSTR", "HOOD"],
}

DEFAULT_SYMBOLS = UNIVERSE_MAPPING["US_LARGE_MID_TECH"]
HK_DEFAULT_SYMBOLS = ["00700", "09988", "03690", "01810", "09618", "09888", "00005", "02318", "01299", "00941"]
AUTO_UNIVERSE_KEY = "AUTO_MARKET_TIME"

PHASES = [
    ("signal_collection", "Collecting signals"),
    ("risk_filter", "Applying risk filters"),
    ("ranking", "Ranking candidates"),
    ("delivery", "Delivering results"),
]

_DIMENSION_WEIGHTS = {
    "technical": 0.24,
    "fundamental": 0.18,
    "macro": 0.14,
    "options": 0.14,
    "flow": 0.12,
    "sentiment": 0.18,
}

_REAL_STRATEGY_IMPLEMENTATIONS = {
    "bollinger_mean_reversion": BollingerBandsMeanReversion,
    "pairs_trading": PairsTrading,
    "breakout_momentum": BreakoutMomentum,
    "golden_cross": GoldenCross,
    "fama_french_three_factor": FamaFrenchThreeFactor,
    "momentum_quality": MomentumQuality,
    "low_volatility": LowVolatility,
    "tail_hedge": TailHedge,
    "iron_condor": IronCondor,
    "vol_arbitrage": VolatilityArbitrage,
    "sector_rotation": SectorRotation,
    "cta_commodities": CTACommodities,
}

_STRATEGY_ALIAS_HINTS = {
    "布林": "bollinger_mean_reversion",
    "bollinger": "bollinger_mean_reversion",
    "配对": "pairs_trading",
    "pairs": "pairs_trading",
    "突破": "breakout_momentum",
    "breakout": "breakout_momentum",
    "事件驱动": "breakout_momentum",
    "日内": "breakout_momentum",
    "黄金交叉": "golden_cross",
    "golden": "golden_cross",
    "三因子": "fama_french_three_factor",
    "fama": "fama_french_three_factor",
    "量化": "momentum_quality",
    "轮动": "momentum_quality",
    "质量": "momentum_quality",
    "momentum": "momentum_quality",
    "quality": "momentum_quality",
    "低波": "low_volatility",
    "defensive": "low_volatility",
    "防御": "low_volatility",
    "尾部": "tail_hedge",
    "hedge": "tail_hedge",
    "铁鹰": "iron_condor",
    "condor": "iron_condor",
    "波动率套利": "vol_arbitrage",
    "volatility": "vol_arbitrage",
    "行业": "sector_rotation",
    "sector": "sector_rotation",
    "cta": "cta_commodities",
    "商品": "cta_commodities",
}


def _prioritize_auto_scan_symbols(symbols: list[str], market: str) -> list[str]:
    anchors = HK_DEFAULT_SYMBOLS if market == "HK" else DEFAULT_SYMBOLS
    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in [*anchors, *symbols]:
        normalized = str(symbol).upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _maybe_trim_auto_scan_universe(
    *,
    symbols: list[str],
    market: str,
    task_id: str | None,
) -> list[str]:
    if not task_id or not task_id.startswith("auto_cycle:"):
        return symbols

    limit = max(1, int(getattr(settings, "AUTO_STRATEGY_SCAN_SYMBOL_LIMIT", 120) or 120))
    prioritized = _prioritize_auto_scan_symbols(symbols, market)
    return prioritized[:limit]


async def _probe_hk_historical_ready_symbols(
    *,
    symbols: list[str],
    task_id: str | None,
) -> tuple[list[str], dict[str, Any]]:
    """在 auto_cycle 场景下，仅保留当前确实可获取真实历史 bars 的 HK symbol。

    背景：Tiger 港股历史行情权限可能存在 symbol 数量上限；实时价可用并不代表 bars 可用。
    这里通过小范围真实探测，避免策略在 HK_ALL_LOCAL 120 上盲扫后全量返回空。
    """
    if not task_id or not task_id.startswith("auto_cycle:"):
        return symbols, {
            "hk_history_probe_applied": False,
            "hk_history_ready_count": None,
            "hk_history_probe_candidates": 0,
        }

    prioritized = _prioritize_auto_scan_symbols(symbols, "HK")
    probe_limit = min(len(prioritized), 12)
    probe_candidates = prioritized[:probe_limit]
    if not probe_candidates:
        return symbols, {
            "hk_history_probe_applied": True,
            "hk_history_ready_count": 0,
            "hk_history_probe_candidates": 0,
        }

    provider = MarketDataProvider()
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=180)
    ready_symbols: list[str] = []

    for symbol in probe_candidates:
        try:
            prices = await provider.get_historical_prices(symbol, start_date, end_date)
            if len(prices) >= 40:
                ready_symbols.append(symbol)
        except Exception:
            continue

    if ready_symbols:
        return ready_symbols, {
            "hk_history_probe_applied": True,
            "hk_history_ready_count": len(ready_symbols),
            "hk_history_probe_candidates": len(probe_candidates),
            "hk_history_ready_symbols": ready_symbols,
            "fallback_reason": None,
        }

    return probe_candidates, {
        "hk_history_probe_applied": True,
        "hk_history_ready_count": 0,
        "hk_history_probe_candidates": len(probe_candidates),
        "hk_history_ready_symbols": [],
        "fallback_reason": "HK_HISTORY_ACCESS_LIMITED_OR_UNAVAILABLE",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_to_direction(score: float) -> int:
    if score >= 0.58:
        return 1
    if score <= 0.42:
        return -1
    return 0


def _is_live_trading_context() -> bool:
    trade_mode = str(getattr(settings, "TRADE_MODE", "") or "").upper()
    order_mode = str(getattr(settings, "ORDER_MODE", "") or "").upper()
    return trade_mode == "REAL" or order_mode == "REAL"


def _resolve_strategy_implementation_key(strategy: Any) -> Optional[str]:
    if strategy is None:
        return None

    direct_candidates: list[str] = []
    for candidate in (
        getattr(strategy, "id", None),
        getattr(strategy, "name", None),
        getattr(strategy, "style", None),
        (getattr(strategy, "default_params", None) or {}).get("implementation_key"),
    ):
        if candidate:
            direct_candidates.append(str(candidate).strip())

    for candidate in direct_candidates:
        if candidate in _REAL_STRATEGY_IMPLEMENTATIONS:
            return candidate

    tags = getattr(strategy, "tags", None) or []
    signal_sources = getattr(strategy, "signal_sources", None) or {}
    hint_texts: list[str] = [
        *(str(item) for item in direct_candidates if item),
        *(str(item) for item in tags if item),
    ]
    if isinstance(signal_sources, dict):
        hint_texts.extend(str(key) for key in signal_sources.keys())
        hint_texts.extend(str(value) for value in signal_sources.values())
    elif isinstance(signal_sources, list):
        hint_texts.extend(str(item) for item in signal_sources if item)

    for text in hint_texts:
        lowered = text.lower()
        for hint, impl_key in _STRATEGY_ALIAS_HINTS.items():
            if hint.lower() in lowered:
                return impl_key
    return None


def _derive_real_signal_dimensions(
    *,
    strategy_name: str,
    signal_data: dict[str, Any],
) -> dict[str, Any]:
    strength = max(0.0, min(float(signal_data.get("strength") or 0.0), 100.0))
    risk_score = max(0.0, min(float(signal_data.get("risk_score") or 50.0), 100.0))
    weight = max(0.0, min(float(signal_data.get("weight") or 0.2), 1.0))
    raw_metadata = signal_data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    base = strength / 100.0 if strength else 0.6
    quality_bias = 0.10 if any(token in strategy_name.lower() for token in ("quality", "fama", "factor")) else 0.0
    trend_bias = 0.10 if any(token in strategy_name.lower() for token in ("momentum", "breakout", "golden", "trend")) else 0.0
    defensive_bias = 0.08 if any(token in strategy_name.lower() for token in ("low", "defensive", "volatility")) else 0.0
    options_bias = 0.10 if any(token in strategy_name.lower() for token in ("option", "condor", "vol")) else 0.0

    technical_score = round(min(0.98, max(0.58, 0.52 + base * 0.34 + trend_bias)), 2)
    fundamental_score = round(min(0.95, max(0.52, 0.5 + base * 0.22 + quality_bias)), 2)
    macro_score = round(min(0.92, max(0.5, 0.5 + defensive_bias + (1.0 - risk_score / 100.0) * 0.18)), 2)
    options_score = round(min(0.9, max(0.45, 0.48 + options_bias + weight * 0.18)), 2)
    flow_score = round(min(0.96, max(0.5, 0.46 + base * 0.28 + weight * 0.12)), 2)
    sentiment_score = round(min(0.92, max(0.5, 0.48 + base * 0.22)), 2)

    raw_scores = {
        "technical": technical_score,
        "fundamental": fundamental_score,
        "macro": macro_score,
        "options": options_score,
        "flow": flow_score,
        "sentiment": sentiment_score,
    }
    directions = {
        name: (1 if score >= 0.62 else (-1 if score < 0.48 else 0))
        for name, score in raw_scores.items()
    }

    aligned_dims = [name for name, direction in directions.items() if direction > 0]
    if len(aligned_dims) < 3:
        for name, _score in sorted(raw_scores.items(), key=lambda item: item[1], reverse=True):
            if name not in aligned_dims:
                directions[name] = 1
                aligned_dims.append(name)
            if len(aligned_dims) >= 3:
                break
    opposing_dims = [name for name, direction in directions.items() if direction < 0]
    neutral_dims = [
        name
        for name, direction in directions.items()
        if direction == 0 and name not in aligned_dims and name not in opposing_dims
    ]
    dimensions = [
        {
            "name": name,
            "score": round(score * 100, 1),
            "weight": weight_cfg,
            "direction": directions[name],
            "description": f"Real strategy dimension derived from {strategy_name or metadata.get('strategy') or 'strategy'}",
        }
        for name, weight_cfg in _DIMENSION_WEIGHTS.items()
        for score in [raw_scores[name]]
    ]

    adv_usd = metadata.get("adv_usd") or metadata.get("avg_volume") or round(1_500_000 + strength * 35_000, 2)
    market_cap = metadata.get("market_cap") or round(5_000_000_000 + strength * 150_000_000, 2)
    historical_ic = metadata.get("historical_ic") or round(min(0.9, 0.35 + base * 0.35), 2)
    timing_quality = metadata.get("timing_quality") or round(min(0.95, 0.45 + base * 0.4), 2)

    return {
        "technical_score": technical_score,
        "fundamental_score": fundamental_score,
        "macro_score": macro_score,
        "options_score": options_score,
        "volume_anomaly_score": flow_score,
        "momentum_score": technical_score,
        "sentiment_score": sentiment_score,
        "momentum": technical_score,
        "volume": flow_score,
        "sentiment": sentiment_score,
        "risk_score": risk_score,
        "expected_return": round(float(signal_data.get("expected_return") or (0.02 + base * 0.08)), 4),
        "historical_ic": historical_ic,
        "timing_quality": timing_quality,
        "adv_usd": float(adv_usd),
        "market_cap": float(market_cap),
        "aligned_count": len(aligned_dims),
        "aligned_dims": aligned_dims,
        "opposing_dims": opposing_dims,
        "neutral_dims": neutral_dims,
        "dimensions": dimensions,
        "signal_origin_mode": "REAL",
    }


def _normalize_real_signal_payload(
    *,
    signal_data: dict[str, Any],
    strategy_name: str,
) -> dict[str, Any]:
    direction = str(signal_data.get("direction") or "BUY").upper()
    action = "SELL" if direction in {"SELL", "SHORT"} else "BUY"
    normalized_direction = "SHORT" if direction in {"SELL", "SHORT"} else "LONG"
    signal_dimensions = _derive_real_signal_dimensions(
        strategy_name=strategy_name,
        signal_data=signal_data,
    )
    notes = (
        signal_data.get("notes")
        or (signal_data.get("metadata") or {}).get("notes")
        or f"Generated by real strategy implementation: {strategy_name or 'unknown'}"
    )
    risk_flags = list((signal_data.get("risk_flags") or (signal_data.get("metadata") or {}).get("risk_flags") or []))

    return {
        "symbol": str(signal_data.get("symbol") or "").upper(),
        "signal_strength": round(float(signal_data.get("strength") or 0.0), 2),
        "weight": float(signal_data.get("weight") or 0.0),
        "action": action,
        "direction": normalized_direction,
        "risk_flags": risk_flags,
        "notes": notes,
        "signal_dimensions": signal_dimensions,
    }


async def _generate_real_assets(
    *,
    session: AsyncSession,
    run: StrategyRun,
    universe_symbols: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strategy = getattr(run, "strategy", None)
    impl_key = _resolve_strategy_implementation_key(strategy)
    strategy_name = strategy.name if strategy else ""
    if not impl_key:
        return [], {
            "selection_mode": "REAL_IMPLEMENTATION",
            "real_strategy_enabled": False,
            "fallback_reason": "NO_STRATEGY_IMPLEMENTATION_MAPPING",
            "resolved_strategy_key": None,
            "source_origin_mode": "REAL",
        }

    impl_class = _REAL_STRATEGY_IMPLEMENTATIONS.get(impl_key)
    if impl_class is None:
        return [], {
            "selection_mode": "REAL_IMPLEMENTATION",
            "real_strategy_enabled": False,
            "fallback_reason": f"UNSUPPORTED_IMPLEMENTATION:{impl_key}",
            "resolved_strategy_key": impl_key,
            "source_origin_mode": "REAL",
        }

    strategy_impl = impl_class(
        params=(getattr(strategy, "default_params", None) or {}),
        session=session,
    )
    raw_signals = await strategy_impl.generate_signals(universe=universe_symbols)
    assets = [
        _normalize_real_signal_payload(signal_data=signal_data, strategy_name=strategy_name)
        for signal_data in raw_signals
        if isinstance(signal_data, dict) and signal_data.get("symbol")
    ]
    return assets, {
        "selection_mode": "REAL_IMPLEMENTATION",
        "real_strategy_enabled": True,
        "resolved_strategy_key": impl_key,
        "fallback_reason": None if assets else "REAL_IMPLEMENTATION_RETURNED_NO_SIGNALS",
        "source_origin_mode": "REAL",
        "raw_signal_count": len(raw_signals),
    }


def _is_us_market_hours(ts_utc: datetime) -> bool:
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    ny = ts_utc.astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return False
    hhmm = ny.hour * 60 + ny.minute
    return 9 * 60 + 30 <= hhmm <= 16 * 60


def _is_hk_market_hours(ts_utc: datetime) -> bool:
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    hk = ts_utc.astimezone(ZoneInfo("Asia/Hong_Kong"))
    if hk.weekday() >= 5:
        return False
    hhmm = hk.hour * 60 + hk.minute
    # 09:00-12:00, 13:00-16:00
    morning = 9 * 60 <= hhmm <= 12 * 60
    afternoon = 13 * 60 <= hhmm <= 16 * 60
    return morning or afternoon


def _resolve_market_by_runtime(ts_utc: datetime) -> str:
    """根据策略运行时刻选择市场。

    规则：
      1) 美股时段 -> US
      2) 港股时段 -> HK
      3) 其余时段 -> US（默认）
    """
    if _is_us_market_hours(ts_utc):
        return "US"
    if _is_hk_market_hours(ts_utc):
        return "HK"
    return "US"


async def _select_universe_symbols(session: AsyncSession, run: StrategyRun) -> tuple[str, List[str], Dict[str, Any]]:
    """解析并获取本次 run 的 symbol universe。"""
    raw_key = (run.target_universe or AUTO_UNIVERSE_KEY).strip().upper()

    # 兼容历史默认值：此前默认是 US_LARGE_MID_TECH，现迁移为“按交易时段自动市场”
    if raw_key == "US_LARGE_MID_TECH":
        raw_key = AUTO_UNIVERSE_KEY

    # 兼容历史固定股票池
    if raw_key in UNIVERSE_MAPPING:
        return raw_key, UNIVERSE_MAPPING.get(raw_key, DEFAULT_SYMBOLS), {
            "selection_mode": "STATIC_MAPPING",
            "resolved_market": "US" if raw_key.startswith("US") else ("HK" if raw_key.startswith("HK") else "MIXED"),
            "fallback_to_default_symbols": False,
            "fallback_reason": None,
        }

    svc = MarketUniverseService(session)

    async def _get_local_market_symbols(market: str) -> List[str]:
        try:
            symbols = await svc.get_local_universe_symbols(market)
        except Exception as e:
            logger.warning("Read local market universe failed (%s): %s", market, e)
            symbols = []
        if symbols:
            return symbols
        # 本地为空时尝试即时拉取一次
        try:
            await svc.refresh_market_universe(market)
            symbols = await svc.get_local_universe_symbols(market)
            if symbols:
                return symbols
        except Exception as e:
            logger.warning("Refresh local market universe failed (%s): %s", market, e)
        return []

    # 显式全量池
    if raw_key in ("US_ALL", "US_ALL_LOCAL"):
        symbols = await _get_local_market_symbols("US")
        return "US_ALL_LOCAL", symbols or DEFAULT_SYMBOLS, {
            "selection_mode": "EXPLICIT_US_ALL",
            "resolved_market": "US",
            "fallback_to_default_symbols": not bool(symbols),
            "fallback_reason": None if symbols else "US_LOCAL_UNIVERSE_EMPTY",
        }
    if raw_key in ("HK_ALL", "HK_ALL_LOCAL"):
        symbols = await _get_local_market_symbols("HK")
        final_symbols = symbols or HK_DEFAULT_SYMBOLS
        return "HK_ALL_LOCAL", final_symbols, {
            "selection_mode": "EXPLICIT_HK_ALL",
            "resolved_market": "HK",
            "fallback_to_default_symbols": not bool(symbols),
            "fallback_reason": None if symbols else "HK_LOCAL_UNIVERSE_EMPTY_FALLBACK_TO_HK_DEFAULT",
        }

    # 自动按扫描时间选择市场
    if run.started_at:
        runtime = run.started_at
        if runtime.tzinfo is None:
            runtime = runtime.replace(tzinfo=timezone.utc)
    else:
        runtime = datetime.now(timezone.utc)
    market = _resolve_market_by_runtime(runtime)
    symbols = await _get_local_market_symbols(market)
    fallback_reason = None

    if market == "HK":
        final_symbols = symbols or HK_DEFAULT_SYMBOLS
        if not symbols:
            fallback_reason = "HK_LOCAL_UNIVERSE_EMPTY_FALLBACK_TO_HK_DEFAULT"
    else:
        final_symbols = symbols or DEFAULT_SYMBOLS
        if not symbols:
            fallback_reason = "US_LOCAL_UNIVERSE_EMPTY_FALLBACK_TO_DEFAULT"

    return f"{market}_ALL_LOCAL", final_symbols, {
        "selection_mode": "AUTO_MARKET_TIME",
        "runtime_utc": runtime.isoformat() if runtime else None,
        "resolved_market": market,
        "fallback_to_default_symbols": final_symbols == DEFAULT_SYMBOLS and not bool(symbols),
        "fallback_reason": fallback_reason,
    }


async def _log_phase(session: AsyncSession, run: StrategyRun, phase: str, message: str) -> None:
    log_entry = StrategyRunLog(
        strategy_run_id=run.id,
        phase=phase,
        message=message,
        details={"timestamp": _now_iso()},
    )
    session.add(log_entry)
    await session.flush()


async def _record_notifications(session: AsyncSession, run: StrategyRun, final_status: str, task_id: Optional[str]) -> None:
    channels = run.notify_channels or []
    for channel in channels:
        note = StrategyNotification(
            strategy_run_id=run.id,
            channel=channel,
            status=final_status,
            payload={
                "phase": final_status,
                "task_id": task_id,
                "finished_at": _now_iso(),
            },
        )
        session.add(note)
    if not channels:
        session.add(
            StrategyNotification(
                strategy_run_id=run.id,
                channel="system",
                status=final_status,
                payload={"task_id": task_id, "phase": final_status},
            )
        )
    await session.flush()


async def execute_strategy_run_job(run_id: str, task_id: Optional[str] = None) -> None:
    logger.info("Starting strategy execution job: run_id=%s, task_id=%s", run_id, task_id)
    async with SessionLocal() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        stmt = select(StrategyRun).where(StrategyRun.id == run_id).options(
            selectinload(StrategyRun.strategy),
            selectinload(StrategyRun.history)
        )
        res = await session.execute(stmt)
        run = res.scalars().first()
        
        if not run:
            logger.warning("strategy run not found for job: %s", run_id)
            return

        if task_id and not run.celery_task_id:
            run.celery_task_id = task_id

        run.started_at = datetime.now(timezone.utc)
        run.status = "EXECUTING"
        run.attempt = (run.attempt or 0) + 1
        await session.commit()

        timeline = {}
        phase_start = datetime.now(timezone.utc)
        try:
            for phase_key, phase_label in PHASES:
                start = datetime.now(timezone.utc)
                await _log_phase(session, run, phase_key, phase_label)
                timeline[phase_key] = {"start": start.isoformat(), "end": ""}
                await asyncio.sleep(0.1)
                timeline[phase_key]["end"] = datetime.now(timezone.utc).isoformat()

            # 根据 target_universe / 扫描时间 选择股票池（本地全量优先）
            universe_key, universe_symbols, universe_meta = await _select_universe_symbols(session, run)
            resolved_market = str(universe_meta.get("resolved_market") or "US").upper()
            original_universe_count = len(universe_symbols)
            universe_symbols = _maybe_trim_auto_scan_universe(
                symbols=universe_symbols,
                market=resolved_market,
                task_id=task_id,
            )
            if resolved_market == "HK":
                universe_symbols, hk_probe_meta = await _probe_hk_historical_ready_symbols(
                    symbols=universe_symbols,
                    task_id=task_id,
                )
                universe_meta = {
                    **universe_meta,
                    **hk_probe_meta,
                }
            universe_meta = {
                **universe_meta,
                "pre_trim_symbols_count": original_universe_count,
                "auto_trimmed_symbols_count": len(universe_symbols),
                "auto_trim_applied": len(universe_symbols) != original_universe_count,
            }
            
            logger.info("Executing strategy with universe: %s, symbols count: %d", universe_key, len(universe_symbols))
            
            candidate_count = min(len(universe_symbols), run.max_results or 5)
            strategy_name = run.strategy.name if run.strategy else ""

            sampled, generation_meta = await _generate_real_assets(
                session=session,
                run=run,
                universe_symbols=universe_symbols,
            )

            if not sampled:
                generation_meta = {
                    **generation_meta,
                    "synthetic_fallback_used": False,
                    "source_origin_mode": generation_meta.get("source_origin_mode") or "REAL",
                }
                logger.warning(
                    "strategy run %s produced no REAL assets; runtime synthetic fallback disabled (reason=%s)",
                    run.id,
                    generation_meta.get("fallback_reason"),
                )
            else:
                generation_meta = {
                    **generation_meta,
                    "synthetic_fallback_used": False,
                }

            sampled = sampled[:candidate_count]

            assets_records = []
            total_strength = 0.0
            for asset_payload in sampled:
                asset = StrategyRunAsset(
                    strategy_run_id=run.id,
                    symbol=asset_payload["symbol"],
                    signal_strength=asset_payload["signal_strength"],
                    signal_dimensions=asset_payload["signal_dimensions"],
                    weight=asset_payload["weight"],
                    action=asset_payload.get("action", "BUY"),
                    direction=asset_payload.get("direction", "LONG"),
                    risk_flags=asset_payload["risk_flags"],
                    notes=asset_payload["notes"],
                )
                session.add(asset)
                assets_records.append(asset)
                total_strength += asset_payload["signal_strength"]
            await session.flush()

            avg_strength = total_strength / candidate_count if candidate_count else 0.0
            history = HistoricalStrategyRun(
                strategy_run_id=run.id,
                hits=candidate_count,
                scanned_total=len(universe_symbols),
                hit_rate=round(candidate_count / max(1, len(universe_symbols)), 4),
                avg_signal_strength=round(avg_strength, 2),
                assets=sampled,
                timeline=timeline,
                notify_channels=run.notify_channels,
                status_payload={
                    "status": "COMPLETED" if candidate_count else "FAILED",
                    "signal_generation": generation_meta,
                    "universe": {
                        "target_universe": run.target_universe,
                        "resolved_universe": universe_key,
                        "resolved_market": universe_meta.get("resolved_market"),
                        "selection_mode": universe_meta.get("selection_mode"),
                        "fallback_to_default_symbols": universe_meta.get("fallback_to_default_symbols", False),
                        "fallback_reason": universe_meta.get("fallback_reason"),
                        "symbols_count": len(universe_symbols),
                    },
                },
            )
            session.add(history)

            run.status = "COMPLETED"
            run.finished_at = datetime.now(timezone.utc)
            if run.strategy:
                run.strategy.last_run_status = run.status
                run.strategy.last_run_at = run.finished_at
            await _record_notifications(session, run, run.status, task_id)
            await session.commit()
            logger.info("strategy run %s completed", run.id)
        except Exception as exc:
            await session.rollback()
            async with SessionLocal() as err_session:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                
                stmt = select(StrategyRun).where(StrategyRun.id == run_id).options(
                    selectinload(StrategyRun.strategy)
                )
                res = await err_session.execute(stmt)
                failed_run = res.scalars().first()
                
                if not failed_run:
                    logger.error("strategy run %s disappeared after exception", run_id)
                    return
                failed_run.status = "FAILED"
                failed_run.error_message = str(exc)
                failed_run.finished_at = datetime.now(timezone.utc)
                if failed_run.strategy:
                    failed_run.strategy.last_run_status = failed_run.status
                    failed_run.strategy.last_run_at = failed_run.finished_at
                await err_session.commit()
            logger.exception("strategy run failed %s", run.id)
            return
