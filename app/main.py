from fastapi import FastAPI, Depends, Body, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import asyncio
import os

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.models.db import engine, SessionLocal, get_session, redis_client, ensure_mysql_indexes, ensure_mysql_tables

# 初始化系统日志
setup_logging()
from app.engine.auto_hedge_engine import AutoHedgeEngine
from app.services.risk_config_service import RiskConfigService
from app.services.symbol_risk_profile_service import SymbolRiskProfileService
from app.services.trading_plan_service import TradingPlanService
from app.providers.market_data_provider import MarketDataProvider
from app.services.option_exposure_service import OptionExposureService
from app.schemas.ai_state import AiStateView, LimitsView, SymbolBehaviorView, ExposureView
from app.broker.factory import make_option_broker_client
from app.schemas.ai_advice import (
    AiAdviceRequest, 
    AiAdviceResponse, 
    KlineAnalysisRequest, 
    KlineAnalysisResponse, 
    SymbolSearchResponse
)
from app.schemas.scheduler import JobScheduleRequest
from app.services.ai_advice_service import AiAdviceService
from app.services.behavior_scoring_service import BehaviorScoringService
from app.routers import position_macro
from app.routers import api_monitoring
from app.routers import trading_plan
from app.routers import strategy
from app.routers import hotspots
from app.routers import quant_loop  # NEW: 量化交易闭环路由
from app.routers import execution_center  # NEW: 执行中心（Layer 3）
from app.routers import ai_advisor  # AI 交易决策（统一入口）
from app.routers import performance  # NEW: Alpha/Beta性能分析指标
# V9 routers
from app.routers import dashboard as v9_dashboard
from app.routers import dashboard_v2  # V10: 全新Dashboard
from app.routers import equity as v9_equity
from app.routers import journal as v9_journal
from app.routers import alerts as v9_alerts
from app.routers import orders as v9_orders
from app.routers import websocket as v9_websocket
from app.jobs.scheduler import init_scheduler, start_scheduler, shutdown_scheduler, add_job
from app.jobs.data_refresh_jobs import register_all_jobs
from app.jobs.quant_loop_jobs import register_quant_loop_jobs  # NEW: 闭环定时任务
from app.core.proxy import apply_proxy_env, ProxyConfig
from app.core.auth import get_current_user, login_for_access_token
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime
import logging
from app.core.cache import cache

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化调度器，关闭时清理"""
    # 启动时执行
    apply_proxy_env(
        ProxyConfig(
            enabled=settings.PROXY_ENABLED,
            http_proxy=settings.HTTP_PROXY,
            https_proxy=settings.HTTPS_PROXY,
            no_proxy=settings.NO_PROXY,
        )
    )

    scheduler = None
    if settings.ENABLE_SCHEDULER:
        scheduler = init_scheduler()
        register_all_jobs(scheduler)
        register_quant_loop_jobs(scheduler)  # NEW: 注册量化交易闭环任务
        start_scheduler()
        logger.info("Scheduler started with periodic tasks")
    else:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")

    # 启动时检查/创建MySQL表与索引
    try:
        await ensure_mysql_tables()
        await ensure_mysql_indexes()
        if settings.DB_TYPE == "mysql":
            logger.info("MySQL tables/indexes checked and ensured")
    except Exception as e:
        logger.error(f"Failed to ensure MySQL tables/indexes: {e}")
    
    yield
    
    # 关闭时执行
    if settings.ENABLE_SCHEDULER:
        shutdown_scheduler(wait=True)
        logger.info("Scheduler shut down")
    
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")

    # 显式释放数据库异步引擎，避免 aiomysql 在事件循环关闭时触发 __del__ 异常
    try:
        await engine.dispose()
        print("✓ Database engine disposed")
    except Exception as e:
        print(f"⚠ Failed to dispose engine gracefully: {e}")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, default_response_class=ORJSONResponse)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该配置具体的域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法（包括OPTIONS）
    allow_headers=["*"],  # 允许所有请求头
)

# 启用GZip压缩（大响应显著减小体积）
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 挂载导出文件静态目录
os.makedirs(settings.EXPORT_ROOT, exist_ok=True)
app.mount("/exports", StaticFiles(directory=settings.EXPORT_ROOT), name="exports")

# 注册路由（默认受保护，需认证）
app.include_router(position_macro.router, prefix="/api/v1", tags=["持仓评估与宏观风险"], dependencies=[Depends(get_current_user)])
app.include_router(api_monitoring.router, prefix="/api/v1", tags=["API监控"], dependencies=[Depends(get_current_user)])
app.include_router(trading_plan.router, prefix="/api/v1", tags=["交易计划"], dependencies=[Depends(get_current_user)])
app.include_router(hotspots.router, prefix="/api/v1", tags=["市场热点"], dependencies=[Depends(get_current_user)])
app.include_router(strategy.router, prefix="/api/v1", tags=["策略管理"], dependencies=[Depends(get_current_user)])
app.include_router(quant_loop.router, dependencies=[Depends(get_current_user)])  # NEW: 量化交易闭环
app.include_router(execution_center.router, dependencies=[Depends(get_current_user)])  # NEW: 执行中心（Layer 3）
app.include_router(ai_advisor.router, dependencies=[Depends(get_current_user)])  # AI 交易决策
app.include_router(performance.router, dependencies=[Depends(get_current_user)])  # NEW: Alpha/Beta性能分析指标

# V9 路由注册
app.include_router(v9_dashboard.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(dashboard_v2.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])  # V10: 全新Dashboard
app.include_router(v9_equity.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(v9_journal.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(v9_alerts.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(v9_orders.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(v9_websocket.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "mode": settings.TRADE_MODE}


@app.post("/api/v1/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """管理员通过用户名/密码换取 Bearer token（JWT）。"""
    return await login_for_access_token(form_data)


@app.post("/api/v1/run-auto-hedge-once")
async def run_auto_hedge_once(session: AsyncSession = Depends(get_session), current_user: str = Depends(get_current_user)):
    engine = AutoHedgeEngine(session)
    await engine.run_once()
    return {"status": "ok", "detail": "auto-hedge executed (or simulated)"}


@app.get("/api/v1/ai/state", response_model=AiStateView)
async def get_ai_state(
    session: AsyncSession = Depends(get_session),
    window_days: Optional[int] = Query(None, description="窗口期（天），可选，前端可传入以覆盖自动选择"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存"),
    current_user: str = Depends(get_current_user)
):
    """返回当前风控状态 + Greeks 敞口 + 每个标的的行为画像。"""
    print("[GET /ai/state] Starting request...")
    
    # 先获取真实的账户ID（从 Tiger API）
    broker_client = make_option_broker_client()
    account_id = await broker_client.get_account_id()
    print(f"[GET /ai/state] Using account_id: {account_id}")

    # 短TTL缓存（提升高频查询性能）
    cache_key = f"ai_state:{account_id}:{window_days or 'auto'}"
    if not force_refresh:
        cached_state = await cache.get(cache_key)
        if cached_state:
            return cached_state
    
    risk = RiskConfigService(session)
    eff = await risk.get_effective_state(account_id, window_days)
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

    # 计划偏离度（仅针对有计划的标的）
    plan_service = TradingPlanService(session)
    plan_map = await plan_service.get_active_plans_by_symbols(account_id, symbols)
    plan_deviation_map = {}
    if plan_map:
        market_provider = MarketDataProvider()

        async def _price(sym: str):
            try:
                return await market_provider.get_current_price(sym)
            except Exception:
                return None

        price_tasks = {sym: asyncio.create_task(_price(sym)) for sym in plan_map.keys()}
        for sym, task in price_tasks.items():
            price = await task
            plan = plan_map.get(sym)
            if plan and price and float(plan.entry_price) > 0:
                plan_deviation_map[sym] = min(abs(price - float(plan.entry_price)) / float(plan.entry_price) * 100, 100)

    limits_view = LimitsView(
        max_order_notional_usd=eff.limits.max_order_notional_usd,
        max_total_gamma_pct=eff.limits.max_total_gamma_pct,
        max_total_vega_pct=eff.limits.max_total_vega_pct,
        max_total_theta_pct=eff.limits.max_total_theta_pct,
    )

    symbol_views = {}
    for sym in symbols:
        stats = behavior_stats.get(sym)
        plan_deviation = plan_deviation_map.get(sym)
        if stats is None:
            # 没有历史行为数据时，给出中性评分和 0 指标
            discipline_score = 60
            bv = SymbolBehaviorView(
                symbol=sym,
                tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                behavior_score=60,
                sell_fly_score=50,
                overtrade_score=50,
                revenge_score=40,
                discipline_score=discipline_score,
                trade_count=0,
                sell_fly_events=0,
                sell_fly_extra_cost_ratio=0.0,
                overtrade_index=0.0,
                revenge_events=0,
            )
        else:
            discipline_score = stats.behavior_score
            if stats.overtrade_score > 70 and plan_deviation is not None and plan_deviation > 30:
                discipline_score = max(0, discipline_score - 20)
            elif stats.overtrade_score > 70:
                discipline_score = max(0, discipline_score - 10)

            bv = SymbolBehaviorView(
                symbol=sym,
                tier=eff.symbol_behavior_tiers.get(sym, "T2"),
                behavior_score=stats.behavior_score,
                sell_fly_score=stats.sell_fly_score,
                overtrade_score=stats.overtrade_score,
                revenge_score=stats.revenge_trade_score,
                discipline_score=discipline_score,
                trade_count=stats.trade_count,
                sell_fly_events=stats.sell_fly_events,
                sell_fly_extra_cost_ratio=stats.sell_fly_extra_cost_ratio,
                overtrade_index=stats.overtrade_index,
                revenge_events=stats.revenge_events,
            )
        symbol_views[sym] = bv

    ai_state = AiStateView(
        trade_mode=eff.effective_trade_mode.value,
        limits=limits_view,
        exposure=exposure_view,
        symbols=symbol_views,
    )

    # 写入缓存（30秒）
    try:
        payload = ai_state.model_dump() if hasattr(ai_state, "model_dump") else ai_state.dict()
        await cache.set(cache_key, payload, expire=30)
    except Exception:
        pass

    return ai_state


@app.post("/api/v1/ai/advice", response_model=AiAdviceResponse)
async def ai_advice(req: AiAdviceRequest, session: AsyncSession = Depends(get_session), current_user: str = Depends(get_current_user)):
    """AI 决策助手接口。"""
    svc = AiAdviceService(session)
    return await svc.get_advice(req)


@app.get("/api/v1/ai/symbols", response_model=SymbolSearchResponse)
async def search_symbols(
    q: Optional[str] = Query(None, description="搜索关键词"),
    session: AsyncSession = Depends(get_session), 
    current_user: str = Depends(get_current_user)
):
    """模糊搜索美港股标的"""
    svc = AiAdviceService(session)
    return await svc.search_symbols(q)


@app.post("/api/v1/ai/analyze-stock", response_model=KlineAnalysisResponse)
async def analyze_stock_kline(
    req: KlineAnalysisRequest,
    session: AsyncSession = Depends(get_session), 
    current_user: str = Depends(get_current_user)
):
    """多周期K线走势 AI 深度分析"""
    svc = AiAdviceService(session)
    return await svc.analyze_stock_kline(req.symbol)


@app.post("/api/v1/admin/behavior/rebuild")
async def rebuild_behavior_stats(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    async_run: bool = Query(False, description="是否异步执行"),
    current_user: str = Depends(get_current_user)
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

    async def _run_behavior_rebuild_job(run_account_id: str, run_window_days: int):
        async with SessionLocal() as local_session:
            svc = BehaviorScoringService(local_session)
            await svc.run_for_account(run_account_id, run_window_days)

    if async_run:
        if not settings.ENABLE_SCHEDULER:
            raise HTTPException(status_code=400, detail="Scheduler disabled, cannot run async job")
        job_id = f"behavior_rebuild:{account_id}:{int(datetime.now().timestamp())}"
        add_job(
            _run_behavior_rebuild_job,
            trigger="date",
            id=job_id,
            name="behavior_rebuild",
            run_date=datetime.now(),
            args=[account_id, window_days],
        )
        return {
            "status": "scheduled",
            "job_id": job_id,
            "account_id": account_id,
            "window_days": window_days,
        }

    svc = BehaviorScoringService(session)
    metrics_map = await svc.run_for_account(account_id, window_days)

    return {
        "status": "ok",
        "account_id": account_id,
        "window_days": window_days,
        "symbols_processed": list(metrics_map.keys()),
        "metrics": {sym: m.__dict__ for sym, m in metrics_map.items()},
    }


@app.get("/api/v1/admin/scheduler/jobs")
async def get_scheduled_jobs(current_user: str = Depends(get_current_user)):
    """获取所有定时任务状态"""
    from app.jobs.scheduler import get_jobs
    try:
        jobs = get_jobs()
        return {
            "status": "ok",
            "total_jobs": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/v1/admin/scheduler/jobs/{job_id}/pause")
async def pause_scheduled_job(job_id: str, current_user: str = Depends(get_current_user)):
    """暂停指定的定时任务"""
    from app.jobs.scheduler import pause_job
    try:
        pause_job(job_id)
        return {"status": "ok", "message": f"Job {job_id} paused"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/v1/admin/scheduler/jobs/{job_id}/resume")
async def resume_scheduled_job(job_id: str, current_user: str = Depends(get_current_user)):
    """恢复指定的定时任务"""
    from app.jobs.scheduler import resume_job
    try:
        resume_job(job_id)
        return {"status": "ok", "message": f"Job {job_id} resumed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.put("/api/v1/admin/scheduler/jobs/{job_id}/schedule")
async def update_job_schedule(job_id: str, payload: JobScheduleRequest, current_user: str = Depends(get_current_user)):
    """按小时/分钟/时区更新定时任务的触发 cron"""
    from app.jobs.scheduler import reschedule_job, get_job, format_job

    try:
        cron_expr = f"{payload.minute} {payload.hour} * * *"
        reschedule_job(job_id=job_id, cron_expr=cron_expr, timezone=payload.timezone)
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        job_info = format_job(job)
        next_run = job_info.get("next_run_time") or "soon"
        message = f"Job schedule updated successfully. Next run: {next_run}"
        return {"status": "success", "message": message, "job": job_info}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
