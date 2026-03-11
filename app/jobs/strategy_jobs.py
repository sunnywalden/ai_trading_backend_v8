from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import SessionLocal
from app.models.strategy import (
    StrategyRun,
    StrategyRunAsset,
    StrategyRunLog,
    HistoricalStrategyRun,
    StrategyNotification,
)
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_to_direction(score: float) -> int:
    if score >= 0.58:
        return 1
    if score <= 0.42:
        return -1
    return 0


def _build_mock_signal_dimensions(
    *,
    strength: float,
    is_event_driven: bool,
    is_intraday: bool,
    is_quant: bool,
) -> dict[str, Any]:
    technical_score = round(
        random.uniform(0.72, 0.96) if (is_intraday or is_quant) else random.uniform(0.55, 0.9),
        2,
    )
    fundamental_score = round(
        random.uniform(0.65, 0.92) if is_quant else random.uniform(0.48, 0.88),
        2,
    )
    macro_score = round(
        random.uniform(0.62, 0.9) if is_event_driven else random.uniform(0.5, 0.82),
        2,
    )
    options_score = round(
        random.uniform(0.6, 0.9) if (is_intraday or is_quant) else random.uniform(0.45, 0.85),
        2,
    )
    flow_score = round(
        random.uniform(0.7, 0.95) if is_intraday else random.uniform(0.48, 0.84),
        2,
    )
    sentiment_score = round(
        random.uniform(0.68, 0.94) if is_event_driven else random.uniform(0.46, 0.86),
        2,
    )

    raw_scores = {
        "technical": technical_score,
        "fundamental": fundamental_score,
        "macro": macro_score,
        "options": options_score,
        "flow": flow_score,
        "sentiment": sentiment_score,
    }

    directions = {name: _score_to_direction(score) for name, score in raw_scores.items()}
    directions["technical"] = 1

    aligned_dims = [name for name, direction in directions.items() if direction > 0]
    if len(aligned_dims) < 4:
        for name, _score in sorted(raw_scores.items(), key=lambda item: item[1], reverse=True):
            if name not in aligned_dims:
                directions[name] = 1
                aligned_dims.append(name)
            if len(aligned_dims) >= 4:
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
            "weight": weight,
            "direction": directions[name],
            "description": f"Mock {name} dimension for watchtower validation",
        }
        for name, weight in _DIMENSION_WEIGHTS.items()
        for score in [raw_scores[name]]
    ]

    risk_score = round(max(20.0, min(65.0, 100.0 - strength + random.uniform(-5.0, 6.0))), 2)
    expected_return = round(0.03 + ((strength - 60.0) / 1000.0), 4)
    historical_ic = round(random.uniform(0.55, 0.9) if is_quant else random.uniform(0.35, 0.78), 2)
    timing_quality = round(random.uniform(0.62, 0.95) if is_intraday else random.uniform(0.45, 0.84), 2)

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
        "expected_return": expected_return,
        "historical_ic": historical_ic,
        "timing_quality": timing_quality,
        "adv_usd": round(random.uniform(2_000_000, 25_000_000), 2),
        "market_cap": round(random.uniform(800_000_000, 350_000_000_000), 2),
        "aligned_count": len(aligned_dims),
        "aligned_dims": aligned_dims,
        "opposing_dims": opposing_dims,
        "neutral_dims": neutral_dims,
        "dimensions": dimensions,
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


def _sample_assets(count: int, strategy_name: str = "", universe_symbols: Optional[List[str]] = None) -> List[dict]:
    if not universe_symbols:
        universe_symbols = DEFAULT_SYMBOLS
    symbols = random.sample(universe_symbols, min(count, len(universe_symbols)))
    assets = []
    
    # 根据策略名称调整模拟数据
    is_event_driven = "事件驱动" in strategy_name
    is_intraday = "日内" in strategy_name
    is_quant = "量化" in strategy_name

    for symbol in symbols:
        strength = round(random.uniform(75.0, 98.0) if any([is_event_driven, is_intraday, is_quant]) else random.uniform(60.0, 99.0), 2)
        weight = round(random.uniform(0.1, 0.25), 3)
        
        notes = "Generated by strategy engine"
        risk_flags = []
        if is_event_driven:
            notes = random.choice(["Earnings breakout detected", "Macro event impact high", "Post-earnings gap fill"])
            risk_flags = ["HIGH_VOLATILITY"]
        elif is_intraday:
            notes = random.choice(["5min trend reversal", "Volume spike at support", "VAP breakout"])
            risk_flags = ["FAST_MOVE"]
        elif is_quant:
            notes = "Strong 60-day relative strength"
            risk_flags = ["TREND_FOLLOWING"]

        signal_dimensions = _build_mock_signal_dimensions(
            strength=strength,
            is_event_driven=is_event_driven,
            is_intraday=is_intraday,
            is_quant=is_quant,
        )

        asset = {
            "symbol": symbol,
            "signal_strength": strength,
            "weight": weight,
            "action": random.choice(["BUY", "INCREASE", "HOLD"]),
            "direction": "LONG",
            "risk_flags": risk_flags,
            "notes": notes,
            "signal_dimensions": signal_dimensions,
        }
        assets.append(asset)
    return assets


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
            
            logger.info("Executing strategy with universe: %s, symbols count: %d", universe_key, len(universe_symbols))
            
            candidate_count = min(len(universe_symbols), run.max_results or 5)
            strategy_name = run.strategy.name if run.strategy else ""
            sampled = _sample_assets(count=candidate_count, strategy_name=strategy_name, universe_symbols=universe_symbols)

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
