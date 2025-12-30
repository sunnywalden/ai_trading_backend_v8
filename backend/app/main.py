from fastapi import FastAPI, Depends, Body, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.engine.auto_hedge_engine import AutoHedgeEngine
from app.services.risk_config_service import RiskConfigService
from app.services.symbol_risk_profile_service import SymbolRiskProfileService
from app.services.option_exposure_service import OptionExposureService
from app.schemas.ai_state import AiStateView, LimitsView, SymbolBehaviorView, ExposureView
from app.broker.factory import make_option_broker_client
from app.schemas.ai_advice import AiAdviceRequest, AiAdviceResponse
from app.services.ai_advice_service import AiAdviceService
from app.services.behavior_scoring_service import BehaviorScoringService

DATABASE_URL = "sqlite+aiosqlite:///./demo.db"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

app = FastAPI(title=settings.APP_NAME)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@app.get("/health")
async def health():
    return {"status": "ok", "mode": settings.TRADE_MODE}


@app.post("/run-auto-hedge-once")
async def run_auto_hedge_once(session: AsyncSession = Depends(get_session)):
    engine = AutoHedgeEngine(session)
    await engine.run_once()
    return {"status": "ok", "detail": "auto-hedge executed (or simulated)"}


@app.get("/ai/state", response_model=AiStateView)
async def get_ai_state(session: AsyncSession = Depends(get_session), window_days: Optional[int] = Query(None, description="窗口期（天），可选，前端可传入以覆盖自动选择")):
    """返回当前风控状态 + Greeks 敞口 + 每个标的的行为画像。"""
    print("[GET /ai/state] Starting request...")
    
    # 先获取真实的账户ID（从 Tiger API）
    broker_client = make_option_broker_client()
    account_id = await broker_client.get_account_id()
    print(f"[GET /ai/state] Using account_id: {account_id}")
    
    risk = RiskConfigService(session)
    eff = await risk.get_effective_state(account_id)
    print(f"[GET /ai/state] Trade mode: {eff.effective_trade_mode.value}")

    # Greeks 敞口
    expo_svc = OptionExposureService(session, broker_client)
    expo = await expo_svc.get_account_exposure(account_id)
    print(f"[GET /ai/state] Equity: {expo.equity_usd}, Delta: {expo.total_delta_notional_usd}, Gamma: {expo.total_gamma_usd}")
    
    eq = expo.equity_usd or 1.0
    delta_pct = expo.total_delta_notional_usd / eq
    gamma_pct = expo.total_gamma_usd / eq
    vega_pct = expo.total_vega_usd / eq
    theta_pct = expo.total_theta_usd / eq
    short_gamma_pct = expo.short_dte_gamma_usd / eq
    short_theta_pct = expo.short_dte_theta_usd / eq

    exposure_view = ExposureView(
        equity_usd=expo.equity_usd,
        total_delta_notional_usd=expo.total_delta_notional_usd,
        total_gamma_usd=expo.total_gamma_usd,
        total_vega_usd=expo.total_vega_usd,
        total_theta_usd=expo.total_theta_usd,
        short_dte_gamma_usd=expo.short_dte_gamma_usd,
        short_dte_vega_usd=expo.short_dte_vega_usd,
        short_dte_theta_usd=expo.short_dte_theta_usd,
        delta_pct=delta_pct,
        gamma_pct=gamma_pct,
        vega_pct=vega_pct,
        theta_pct=theta_pct,
        short_dte_gamma_pct=short_gamma_pct,
        short_dte_theta_pct=short_theta_pct,
    )

    # 行为统计
    symbols = list(eff.symbol_behavior_tiers.keys())
    print(f"[GET /ai/state] Symbols from effective_state: {symbols}")
    # window_days: frontend 可传，也可使用数据库自动选择的 eff.window_days
    effective_window = window_days if window_days is not None else eff.window_days
    print(f"[GET /ai/state] window_days param: {window_days}, using: {effective_window}")
    
    prof_svc = SymbolRiskProfileService(session)
    behavior_stats = await prof_svc.get_behavior_stats(account_id, symbols, effective_window)
    print(f"[GET /ai/state] Behavior stats retrieved for {len(behavior_stats)} symbols: {list(behavior_stats.keys())}")

    limits_view = LimitsView(
        max_order_notional_usd=eff.limits.max_order_notional_usd,
        max_total_gamma_pct=eff.limits.max_total_gamma_pct,
        max_total_vega_pct=eff.limits.max_total_vega_pct,
        max_total_theta_pct=eff.limits.max_total_theta_pct,
    )

    symbol_views = {}
    for sym in symbols:
        stats = behavior_stats.get(sym)
        if stats is None:
            # 没有历史行为数据时，给出中性评分和 0 指标
            bv = SymbolBehaviorView(
                symbol=sym,
                tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                behavior_score=60,
                sell_fly_score=50,
                overtrade_score=50,
                revenge_score=40,
                trade_count=0,
                sell_fly_events=0,
                sell_fly_extra_cost_ratio=0.0,
                overtrade_index=0.0,
                revenge_events=0,
            )
        else:
            bv = SymbolBehaviorView(
                symbol=sym,
                tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                behavior_score=stats.behavior_score,
                sell_fly_score=stats.sell_fly_score,
                overtrade_score=stats.overtrade_score,
                revenge_score=stats.revenge_trade_score,
                trade_count=stats.trade_count,
                sell_fly_events=stats.sell_fly_events,
                sell_fly_extra_cost_ratio=stats.sell_fly_extra_cost_ratio,
                overtrade_index=stats.overtrade_index,
                revenge_events=stats.revenge_events,
            )
        symbol_views[sym] = bv

    return AiStateView(
        trade_mode=eff.effective_trade_mode.value,
        limits=limits_view,
        exposure=exposure_view,
        symbols=symbol_views,
    )


@app.post("/ai/advice", response_model=AiAdviceResponse)
async def ai_advice(req: AiAdviceRequest, session: AsyncSession = Depends(get_session)):
    """AI 决策助手接口。

    输入：目标描述 + 风险偏好 + 时间维度；
    内部自动聚合当前账户状态（风险限额、Greeks 暴露、行为画像），
    调用 GPT-5.1（或占位逻辑）生成结构化的交易建议和订单草案。
    """
    svc = AiAdviceService(session)
    return await svc.get_advice(req)


@app.post("/admin/behavior/rebuild")
async def rebuild_behavior_stats(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
):
    """重计算最近 N 天的行为评分（基于老虎历史成交 + 盈亏数据）。

    输入 JSON:
    {
        "account_id": "可选，默认 settings.TIGER_ACCOUNT",
        "window_days": 60      # 可选，默认 60
    }
    """
    account_id = payload.get("account_id") or settings.TIGER_ACCOUNT
    window_days = payload.get("window_days", 60)

    svc = BehaviorScoringService(session)
    metrics_map = await svc.run_for_account(account_id, window_days)

    return {
        "status": "ok",
        "account_id": account_id,
        "window_days": window_days,
        "symbols_processed": list(metrics_map.keys()),
        "metrics": {sym: m.__dict__ for sym, m in metrics_map.items()},
    }
