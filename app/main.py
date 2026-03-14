import asyncio
import os
import signal
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.i18n import get_translator
from app.models.db import (
    SessionLocal,
    engine,
    ensure_mysql_indexes,
    ensure_mysql_schema_updates,
    ensure_mysql_tables,
    get_session,
    redis_client,
)

# 初始化系统日志
setup_logging()
import logging
from datetime import UTC, datetime

from fastapi.security import OAuth2PasswordRequestForm

from app.broker.factory import make_option_broker_client
from app.core.auth import get_current_user, login_for_access_token
from app.core.cache import cache
from app.core.proxy import ProxyConfig, apply_proxy_env
from app.engine.auto_hedge_engine import AutoHedgeEngine
from app.jobs.data_refresh_jobs import register_all_jobs
from app.jobs.ghost_trade_jobs import update_ghost_trades_pnl  # V10.4.2: 幽灵交易追踪
from app.jobs.paper_graduation_job import (
    register_paper_graduation_job,
)  # V10.1: Paper 毕业检查
from app.jobs.quant_loop_jobs import register_quant_loop_jobs  # NEW: 闭环定时任务
from app.jobs.regime_jobs import register_regime_jobs  # V10.2-M1: 市场体制分类任务
from app.jobs.scheduler import (
    add_job,
    init_scheduler,
    pause_scheduler,
    shutdown_scheduler,
    start_scheduler,
)
from app.jobs.task_config_jobs import register_task_config_jobs  # V10: 动态配置同步任务
from app.providers.market_data_provider import MarketDataProvider, market_data_provider

# hotspots removed in V11.1.1 – no active frontend caller, frontend redirects to /opportunities
# stress_test removed in V11.1.1 – endpoints migrated to backtest.py (see /backtest/stress-test/)
# execution_center removed in V11.1.1 – no active frontend caller (PlanEditDialog is orphan)
# V9 routers
# V10.3.3 新路由
# V10.2-M2-M8 新路由
# V10.2 新路由
# V10 新路由
# ai_advisor removed in V11.1.1 – endpoints migrated to autonomy.py (sunset)
from app.routers import ai_hub  # V10.3.3: AI 中枢 2.0
from app.routers import alpha_lab  # V10.5.1: Alpha Lab
from app.routers import attribution  # V10.2-M5: 交易归因
from app.routers import autonomy  # V10: AI自主中枢
from app.routers import backtest  # V10: 回测引擎
from app.routers import capacity_arbiter  # V10.5.2: 席位竞争仲裁
from app.routers import copilot  # V10: AI助手
from app.routers import dashboard_v2  # V10: 全新Dashboard
from app.routers import etf  # V10.1: ETF自选列表
from app.routers import events  # V10.2-M2: 事件日历围栏
from app.routers import execution_algo  # V10: 算法执行
from app.routers import execution_policy  # V10.5.1: Execution Policy Console
from app.routers import governance  # V10.5.1: Promotion Pipeline
from app.routers import insights  # V10.2-M6: AI 洞察
from app.routers import lifecycle  # V10.3: 交易生命周期中心
from app.routers import live_safety  # V10.5.1: M4 Live Safety Guard
from app.routers import market_universe  # 市场全量池状态
from app.routers import observability  # V10.3.3: 可观测性 2.0
from app.routers import options_analysis  # V10: 期权分析
from app.routers import order_book  # V10.3: 智能订单簿
from app.routers import paper_trading  # V10: 模拟盘
from app.routers import performance  # NEW: Alpha/Beta性能分析指标
from app.routers import portfolio  # V10: 组合优化
from app.routers import position_eval  # 持仓评估任务
from app.routers import position_lifecycle  # V10.2-M3: 动态仓位
from app.routers import positions  # V10.4.4: Position-centric 生命周期
from app.routers import quant_loop  # NEW: 量化交易闭环路由
from app.routers import regime  # V10.2-M1: 市场体制感知
from app.routers import signal_fusion  # V10.2-M4: 六维信号融合
from app.routers import signal_quality  # V10.4.2: 信号精英化漏斗
from app.routers import system_monitor  # V10.4.3: 系统监控增强
from app.routers import task_config  # V10: 统一任务配置管理
from app.routers import war_room  # V10.3.3: 战情室
from app.routers import alerts as v9_alerts
from app.routers import api_monitoring
from app.routers import dashboard as v9_dashboard
from app.routers import equity as v9_equity
from app.routers import journal as v9_journal
from app.routers import orders as v9_orders
from app.routers import position_macro, strategy, trading_plan
from app.routers import websocket as v9_websocket
from app.schemas.ai_advice import (
    AiAdviceRequest,
    AiAdviceResponse,
    KlineAnalysisRequest,
    KlineAnalysisResponse,
    SymbolSearchResponse,
)
from app.schemas.ai_state import (
    AiStateView,
    ExposureView,
    LimitsView,
    SymbolBehaviorView,
)
from app.schemas.scheduler import JobScheduleRequest
from app.services.ai_advice_service import AiAdviceService
from app.services.behavior_scoring_service import BehaviorScoringService
from app.services.option_exposure_service import OptionExposureService
from app.services.risk_config_service import RiskConfigService
from app.services.symbol_risk_profile_service import SymbolRiskProfileService
from app.services.trading_plan_service import TradingPlanService

logger = logging.getLogger(__name__)

_tracked_startup_tasks: set[asyncio.Task] = set()
_original_signal_handlers: dict[int, Any] = {}
_shutdown_in_progress = False
_shutdown_cleanup_task: asyncio.Task | None = None


def _task_origin(task: asyncio.Task) -> str:
    try:
        coro = task.get_coro()
        code = getattr(coro, "cr_code", None)
        if code is not None:
            return str(getattr(code, "co_filename", "") or "")
    except Exception:
        pass
    return ""


def _is_app_owned_task(task: asyncio.Task) -> bool:
    origin = _task_origin(task)
    if not origin:
        return False
    workspace_app_root = "/Users/admin/IdeaProjects/ai_trading_backend_v8/app/"
    workspace_scripts_root = "/Users/admin/IdeaProjects/ai_trading_backend_v8/scripts/"
    return origin.startswith(workspace_app_root) or origin.startswith(
        workspace_scripts_root
    )


def _track_startup_task(task: asyncio.Task) -> None:
    _tracked_startup_tasks.add(task)

    def _cleanup(done_task: asyncio.Task) -> None:
        _tracked_startup_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.info("[StartupTask] %s cancelled", done_task.get_name())
        except Exception as exc:
            logger.warning("[StartupTask] %s failed: %s", done_task.get_name(), exc)

    task.add_done_callback(_cleanup)


def _spawn_startup_task(coro, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _track_startup_task(task)
    return task


async def _cancel_tracked_startup_tasks() -> None:
    tasks = list(_tracked_startup_tasks)
    if not tasks:
        return

    for task in tasks:
        if not task.done():
            task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)


async def _force_cancel_pending_tasks(delay: float = 2.0) -> None:
    await asyncio.sleep(delay)

    current = asyncio.current_task()
    pending: list[asyncio.Task] = []
    for task in asyncio.all_tasks():
        if task is current or task.done():
            continue
        if task is _shutdown_cleanup_task:
            continue
        if not _is_app_owned_task(task):
            continue
        pending.append(task)

    if not pending:
        return

    task_names = [f"{task.get_name()}@{_task_origin(task)}" for task in pending]
    logger.warning("[Shutdown] Force-cancelling pending tasks: %s", task_names)
    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)


def _begin_fast_shutdown(source: str) -> None:
    global _shutdown_in_progress, _shutdown_cleanup_task
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True

    logger.info("[Shutdown] Fast shutdown triggered by %s", source)

    try:
        from app.routers.websocket import close_all_websockets, mark_shutdown_started

        mark_shutdown_started()
        loop = asyncio.get_running_loop()
        loop.create_task(close_all_websockets(), name="shutdown-close-websockets")
        if _shutdown_cleanup_task is None or _shutdown_cleanup_task.done():
            _shutdown_cleanup_task = loop.create_task(
                _force_cancel_pending_tasks(),
                name="shutdown-force-cancel-pending-tasks",
            )
    except Exception as exc:
        logger.warning("[Shutdown] Failed to schedule websocket/task cleanup: %s", exc)

    if not settings.ENABLE_SCHEDULER:
        return

    try:
        pause_scheduler()
    except Exception as exc:
        logger.warning("[Shutdown] Failed to pause scheduler: %s", exc)

    try:
        shutdown_scheduler(wait=False)
    except Exception as exc:
        logger.warning("[Shutdown] Failed to shut down scheduler quickly: %s", exc)


def _install_signal_handlers() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(sig)
        _original_signal_handlers[sig] = previous

        def _handler(signum, frame, *, _previous=previous):
            _begin_fast_shutdown(signal.Signals(signum).name)
            if callable(_previous):
                return _previous(signum, frame)
            return None

        signal.signal(sig, _handler)


def _restore_signal_handlers() -> None:
    for sig, handler in list(_original_signal_handlers.items()):
        try:
            signal.signal(sig, handler)
        except Exception:
            pass
    _original_signal_handlers.clear()


def _log_regime_bootstrap_result(result: dict | None) -> None:
    if not isinstance(result, dict):
        logger.warning(
            "[WarmUp] regime bootstrap returned unexpected result: %r", result
        )
        return

    if result.get("skipped"):
        logger.warning(
            "[WarmUp] regime bootstrap skipped: reason=%s error=%s",
            result.get("reason"),
            result.get("error"),
        )
        return

    logger.info("[WarmUp] ✓ Market regime refreshed")


def _log_technical_warmup_result(result: dict | None) -> None:
    if not isinstance(result, dict):
        logger.warning(
            "[WarmUp] technical indicator warm-up returned unexpected result: %r",
            result,
        )
        return
    if not result.get("success"):
        logger.warning(
            "[WarmUp] technical indicator warm-up failed: %s", result.get("error")
        )
        return
    success_count = int(result.get("success_count") or 0)
    attempted = list(result.get("symbols_attempted") or [])
    if success_count <= 0:
        logger.warning(
            "[WarmUp] technical indicator warm-up deferred: no symbols refreshed (attempted=%s)",
            attempted,
        )
        return
    logger.info("[WarmUp] ✓ Technical indicators seeded (%d symbols)", success_count)


def _log_factor_snapshot_warmup_result(result: dict | None) -> None:
    if not isinstance(result, dict):
        logger.warning(
            "[WarmUp] factor snapshot warm-up returned unexpected result: %r", result
        )
        return
    if not result.get("success"):
        logger.warning(
            "[WarmUp] factor snapshot warm-up failed: %s", result.get("error")
        )
        return
    seeded_accounts = int(result.get("seeded_accounts") or 0)
    if seeded_accounts <= 0:
        logger.warning(
            "[WarmUp] factor snapshot warm-up deferred: no account snapshot seeded"
        )
        return
    logger.info(
        "[WarmUp] ✓ Factor exposure snapshot seeded (%d accounts)", seeded_accounts
    )


async def _warm_up_regime_cache() -> None:
    """WarmUp 阶段的 Regime 预热，严格模式下先做输入就绪探测。"""
    try:
        from app.services.regime_classifier import regime_classifier

        _REGIME_STALE_H = 24.0
        async with SessionLocal() as _db:
            _current_regime = await regime_classifier.get_current_regime(_db)
            _regime_stale = (
                _current_regime is None
                or (
                    datetime.now(UTC).replace(tzinfo=None) - _current_regime.created_at
                ).total_seconds()
                / 3600
                > _REGIME_STALE_H
            )
            if not (_regime_stale and settings.REGIME_ENABLED):
                logger.info("[WarmUp] ✓ Market regime cached")
                return

            _reason = "no data" if _current_regime is None else "stale"
            logger.info("[WarmUp] Regime %s, bootstrapping synchronously...", _reason)

            if not getattr(settings, "RUNTIME_ALLOW_DECISION_DEFAULTS", False):
                probe = await regime_classifier.probe_real_inputs_ready()
                if not probe.get("ready"):
                    missing = ", ".join(probe.get("missing") or []) or "unknown"
                    logger.warning(
                        "[WarmUp] regime bootstrap deferred: real inputs not ready (missing=%s)",
                        missing,
                    )
                    return

            try:
                result = await regime_classifier.run(_db)
                _log_regime_bootstrap_result(result)
            except Exception as _re:
                logger.warning(f"[WarmUp] regime bootstrap failed: {_re}")
    except Exception as _e:
        logger.warning(f"[WarmUp] regime warm-up failed: {_e}")


async def _warm_up_caches() -> None:
    """系统启动后异步预热关键缓存，提升用户首次请求响应速度。

    预热项目：
        1. 当前市场体制（Redis）
        2. Dashboard 汇总数据（净值 / 仓位概览）
        3. 宏观风险指标
        4. 活跃告警列表
        5. ETF 标的池最新信号
        6. 待处理交易信号数量
    所有操作均包裹在独立 try/except 中，任何一项失败不影响其他项。
    """
    await asyncio.sleep(5)  # 等待调度器与 DB 连接池完全就绪
    logger.info("[WarmUp] Starting cache pre-warming...")

    # 1. 市场体制（若表为空或超过 24h 未刷新，则立即同步跑一次分类）
    await _warm_up_regime_cache()

    # 2. Dashboard 净值汇总
    try:
        from app.services.dashboard_v2_service import DashboardV2Service  # type: ignore

        async with SessionLocal() as _db:
            svc = DashboardV2Service(_db)
            await svc.get_full_dashboard(settings.TIGER_ACCOUNT)
        logger.info("[WarmUp] ✓ Dashboard summary cached")
    except Exception as _e:
        logger.warning(f"[WarmUp] dashboard warm-up failed: {_e}")

    # 3. 活跃告警
    try:
        from sqlalchemy import text as _text

        from app.models.price_alert import PriceAlert

        async with SessionLocal() as _db:
            await _db.execute(
                _text(
                    f"SELECT COUNT(*) FROM {PriceAlert.__tablename__} "
                    "WHERE alert_status='ACTIVE' LIMIT 1"
                )
            )
        logger.info("[WarmUp] ✓ Alerts cached")
    except Exception as _e:
        logger.warning(f"[WarmUp] alerts warm-up failed: {_e}")

    # 4. ETF 标的池
    try:
        from sqlalchemy import select as _select

        from app.models.etf_watchlist import EtfWatchlist

        async with SessionLocal() as _db:
            await _db.execute(_select(EtfWatchlist).limit(10))
        logger.info("[WarmUp] ✓ ETF pool cached")
    except Exception as _e:
        logger.warning(f"[WarmUp] ETF pool warm-up failed: {_e}")

    # 5. 待处理信号数量（触发 signal_fusion 聚合查询）
    try:
        from sqlalchemy import text as _text

        from app.models.trading_signal import TradingSignal

        async with SessionLocal() as _db:
            await _db.execute(
                _text(
                    f"SELECT COUNT(*) FROM {TradingSignal.__tablename__} "
                    "WHERE status IN ('GENERATED', 'VALIDATED') LIMIT 1"
                )
            )
        logger.info("[WarmUp] ✓ Signal count cached")
    except Exception as _e:
        logger.warning(f"[WarmUp] signal count warm-up failed: {_e}")

    # 6. 事件日历种子（确保宏观事件行存在，避免冷启动 WARNING）
    try:
        from app.services.event_calendar_service import event_calendar_service

        async with SessionLocal() as _db:
            await event_calendar_service.ensure_calendar_seeded(_db, days=7)
        logger.info("[WarmUp] ✓ Event calendar seeded")
    except Exception as _e:
        logger.warning(f"[WarmUp] event calendar warm-up failed: {_e}")

    # 7. 技术指标 / quote freshness 种子（避免启动即出现 quote_data WARNING）
    try:
        from app.jobs.data_refresh_jobs import refresh_technical_indicators_job

        result = await refresh_technical_indicators_job()
        _log_technical_warmup_result(result)
    except Exception as _e:
        logger.warning(f"[WarmUp] technical indicator warm-up failed: {_e}")

    # 8. 因子敞口快照（首次写入，消除 5min 任务间隔内的冷启动 WARNING）
    try:
        from app.jobs.observability_jobs import take_factor_exposure_snapshot

        result = await take_factor_exposure_snapshot()
        _log_factor_snapshot_warmup_result(result)
    except Exception as _e:
        logger.warning(f"[WarmUp] factor snapshot warm-up failed: {_e}")

    logger.info("[WarmUp] Cache pre-warming complete.")


async def _bootstrap_market_universe() -> None:
    """服务启动后异步全量拉取 US/HK 股票池并入库缓存。"""
    # 避免与启动阶段其他初始化竞争连接池
    await asyncio.sleep(3)

    try:
        from app.broker.factory import get_tiger_client

        if not get_tiger_client():
            logger.info(
                "[MarketUniverseBootstrap] Tiger client unavailable, skip startup sync"
            )
            return
    except Exception as e:
        logger.warning(f"[MarketUniverseBootstrap] tiger check failed: {e}")
        return

    try:
        from app.services.market_universe_service import MarketUniverseService

        async with SessionLocal() as session:
            svc = MarketUniverseService(session)
            result = await svc.refresh_all_markets()
            logger.info(f"[MarketUniverseBootstrap] startup sync done: {result}")
    except Exception as e:
        logger.warning(f"[MarketUniverseBootstrap] startup sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化调度器，关闭时清理"""
    global _shutdown_in_progress, _shutdown_cleanup_task
    _shutdown_in_progress = False
    _shutdown_cleanup_task = None
    _install_signal_handlers()
    try:
        from app.routers.websocket import reset_shutdown_state

        reset_shutdown_state()
    except Exception:
        pass

    # 启动时执行
    apply_proxy_env(
        ProxyConfig(
            enabled=settings.PROXY_ENABLED,
            http_proxy=settings.HTTP_PROXY,
            https_proxy=settings.HTTPS_PROXY,
            no_proxy=settings.NO_PROXY,
        )
    )

    # 启动时检查/创建MySQL表与索引
    try:
        await ensure_mysql_tables()
        await ensure_mysql_schema_updates()  # 修复缺少的列
        await ensure_mysql_indexes()
        if settings.DB_TYPE == "mysql":
            logger.info("MySQL tables/indexes checked and ensured")
    except Exception as e:
        logger.error(f"Failed to ensure MySQL tables/indexes: {e}")

    scheduler = None
    if settings.ENABLE_SCHEDULER:
        scheduler = init_scheduler()
        register_all_jobs(scheduler)
        register_quant_loop_jobs(scheduler)  # NEW: 注册量化交易闭环任务
        register_task_config_jobs(scheduler)  # V10: 注册动态配置同步任务
        register_paper_graduation_job(scheduler)  # V10.1: Paper 毕业检查
        register_regime_jobs(scheduler)  # V10.2-M1: 市场体制分类任务
        # V10.2-M2-M8 任务注册
        try:
            from app.jobs.event_jobs import register_event_jobs

            register_event_jobs(scheduler)  # V10.2-M2: 事件日历扫描
        except ImportError:
            pass
        try:
            from app.jobs.insight_jobs import register_insight_jobs

            register_insight_jobs(scheduler)  # V10.2-M6: 每周 AI 洞察
        except ImportError:
            pass
        # V10.3.3 任务注册
        try:
            from app.jobs.observability_jobs import register_observability_jobs

            register_observability_jobs(scheduler)  # V10.3.3: 因子敞口快照 (5min)
        except ImportError:
            pass
        try:
            from app.jobs.equity_jobs import register_equity_jobs

            register_equity_jobs(scheduler)  # V10: 每日美股收盘后权益快照
        except ImportError:
            pass
        try:
            from app.jobs.ai_hub_jobs import register_ai_hub_jobs

            register_ai_hub_jobs(
                scheduler
            )  # V10.3.3: 置信度校准 (08:15) + 权重更新 (EOD)
        except ImportError:
            pass
        try:
            from app.jobs.m1_data_loop_jobs import register_m1_jobs

            register_m1_jobs(scheduler)  # V10.4 M1: actual_return 回填 (02:30 UTC)
        except ImportError:
            pass
        try:
            from app.jobs.m4_health_jobs import register_m4_jobs

            register_m4_jobs(scheduler)  # V10.4 M4: 自主循环 8 项健康检查 (2min)
        except ImportError:
            pass
        try:
            from app.jobs.data_sync_jobs import register_data_sync_jobs

            register_data_sync_jobs(
                scheduler
            )  # V10.4: 数据自动同步 (journal关闭/actual_return/归因)
        except ImportError:
            pass
        try:
            from app.jobs.post_mortem_jobs import register_post_mortem_jobs

            register_post_mortem_jobs(
                scheduler
            )  # V10.5.2: 事后决策剖析自动化（EventBus + 每日兜底）
        except ImportError:
            pass
        # V10.4.2: 幽灵交易每日追踪（美东 16:35，盘后）
        try:
            scheduler.add_job(
                update_ghost_trades_pnl,
                "cron",
                hour=20,  # UTC 20:35 = 美东 16:35（标准时间）
                minute=35,
                id="ghost_trade_daily_update",
                replace_existing=True,
                name="[V10.4.2] 幽灵交易PnL日度更新",
            )
            logger.info(
                "[GhostTradeJob] Registered ghost trade daily update job (20:35 UTC)"
            )
        except Exception as _gj_err:
            logger.warning(f"[GhostTradeJob] Failed to register job: {_gj_err}")
        start_scheduler()
        logger.info("Scheduler started with periodic tasks")

        # V10.2-M1: 首次启动检查，如果没有当前体制数据，则立即进行一次自动分类
        if settings.REGIME_ENABLED:
            try:
                from app.jobs.regime_jobs import run_regime_classification
                from app.models.db import SessionLocal
                from app.services.regime_classifier import regime_classifier

                async with SessionLocal() as db:
                    current = await regime_classifier.get_current_regime(db)
                    if not current:
                        logger.info(
                            "No current market regime found, triggering initial classification..."
                        )
                        # 立即运行一次 (通过 scheduler 异步)
                        scheduler.add_job(
                            run_regime_classification,
                            args=[True],  # force=True
                            id="initial_regime_run",
                        )
            except Exception as e:
                logger.warning(f"Failed to trigger initial regime classification: {e}")
    else:
        logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")

    # V10.2-M1: 注册体制感知事件处理器（EventBus）
    try:
        from app.services.regime_strategy_allocator import (
            register_handlers as _reg_regime_handlers,
        )

        _reg_regime_handlers()
    except Exception as _e:
        logger.warning(f"Failed to register regime event handlers: {_e}")

    # 从 Redis 恢复 AutonomousEngine 暂停/熔断状态（防止重启后丢失互斥标志）
    try:
        from app.services.autonomous_engine import autonomous_engine

        await autonomous_engine.restore_state()
    except Exception as _e:
        logger.warning(f"Failed to restore AutonomousEngine state: {_e}")

    # 异步预热关键缓存（非阻塞 fire-and-forget）
    _spawn_startup_task(_warm_up_caches(), name="startup-cache-warmup")

    # 启动即异步全量同步市场标的（DB + 缓存）
    _spawn_startup_task(
        _bootstrap_market_universe(), name="startup-market-universe-bootstrap"
    )

    yield

    # 关闭时执行
    _begin_fast_shutdown("lifespan")
    await _cancel_tracked_startup_tasks()
    if _shutdown_cleanup_task is not None:
        try:
            await asyncio.shield(_shutdown_cleanup_task)
        except asyncio.CancelledError:
            logger.info("[Shutdown] Cleanup task cancelled during finalization")
    _restore_signal_handlers()

    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")

    # 显式释放数据库异步引擎，避免 aiomysql 在事件循环关闭时触发 __del__ 异常
    try:
        await engine.dispose()
        print("✓ Database engine disposed")
    except Exception as e:
        print(f"⚠ Failed to dispose engine gracefully: {e}")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
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
app.include_router(
    position_macro.router,
    prefix="/api/v1",
    tags=["持仓评估与宏观风险"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    api_monitoring.router,
    prefix="/api/v1",
    tags=["API监控"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    trading_plan.router,
    prefix="/api/v1",
    tags=["交易计划"],
    dependencies=[Depends(get_current_user)],
)
# hotspots.router removed in V11.1.1 (V11.1.1-sunset)
app.include_router(
    strategy.router,
    prefix="/api/v1",
    tags=["策略管理"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    quant_loop.router, dependencies=[Depends(get_current_user)]
)  # NEW: 量化交易闭环
app.include_router(
    task_config.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
# execution_center.router removed in V11.1.1 (V11.1.1-sunset)
# ai_advisor.router removed in V11.1.1 (V11.1.1-sunset)
app.include_router(
    performance.router, dependencies=[Depends(get_current_user)]
)  # NEW: Alpha/Beta性能分析指标
app.include_router(
    alpha_lab.router, dependencies=[Depends(get_current_user)]
)  # V10.5.1: Alpha Lab
app.include_router(
    execution_policy.router, dependencies=[Depends(get_current_user)]
)  # V10.5.1: Execution Policy
app.include_router(
    governance.router, dependencies=[Depends(get_current_user)]
)  # V10.5.1: Promotion Pipeline
app.include_router(
    live_safety.router, dependencies=[Depends(get_current_user)]
)  # V10.5.1: M4 Live Safety Guard

# V9 路由注册 (deprecated=True; will be removed in V11.2)
app.include_router(
    v9_dashboard.router,
    prefix="/api/v1",
    tags=[
        "[DEPRECATED-V9] Dashboard – will be removed in V11.2, use /api/v1/dashboard/"
    ],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    dashboard_v2.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)  # V10: 全新Dashboard
app.include_router(
    v9_equity.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    v9_journal.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    v9_alerts.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    v9_orders.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(v9_websocket.router, prefix="/api/v1")
# V10 新路由注册
app.include_router(
    portfolio.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    etf.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    autonomy.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    backtest.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    copilot.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
# stress_test.router removed in V11.1.1; use /api/v1/backtest/stress-test/ (V11.1.1-migration)
app.include_router(
    paper_trading.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    options_analysis.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    execution_algo.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    position_eval.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
# V10.2 新路由注册
app.include_router(
    regime.router, dependencies=[Depends(get_current_user)]
)  # V10.2-M1: 市场体制感知
# V10.2-M2-M8 路由注册
app.include_router(
    events.router, dependencies=[Depends(get_current_user)]
)  # M2: 事件日历
app.include_router(
    position_lifecycle.router, dependencies=[Depends(get_current_user)]
)  # M3: 动态仓位
app.include_router(
    signal_fusion.router, dependencies=[Depends(get_current_user)]
)  # M4: 信号融合
app.include_router(
    attribution.router, dependencies=[Depends(get_current_user)]
)  # M5: 交易归因
app.include_router(
    insights.router, dependencies=[Depends(get_current_user)]
)  # M6: AI 洞察
app.include_router(
    lifecycle.router, dependencies=[Depends(get_current_user)]
)  # V10.3: 交易生命周期中心
app.include_router(
    order_book.router, dependencies=[Depends(get_current_user)]
)  # V10.3: 智能订单簿
# V10.3.3 新路由注册
app.include_router(
    observability.router, dependencies=[Depends(get_current_user)]
)  # V10.3.3: 可观测性 2.0
app.include_router(
    ai_hub.router, dependencies=[Depends(get_current_user)]
)  # V10.3.3: AI 中枢 2.0
app.include_router(
    war_room.router, dependencies=[Depends(get_current_user)]
)  # V10.3.3: 战情室
app.include_router(
    market_universe.router, prefix="/api/v1", dependencies=[Depends(get_current_user)]
)
app.include_router(
    signal_quality.router, dependencies=[Depends(get_current_user)]
)  # V10.4.2: 信号精英化漏斗
app.include_router(
    capacity_arbiter.router, dependencies=[Depends(get_current_user)]
)  # V10.5.2: 席位竞争仲裁
app.include_router(
    system_monitor.router, dependencies=[Depends(get_current_user)]
)  # V10.4.3: 系统监控增强
app.include_router(
    positions.router, dependencies=[Depends(get_current_user)]
)  # V10.4.4: Position-centric


@app.get("/health")
async def health():
    return {"status": "ok", "mode": settings.TRADE_MODE}


@app.post("/api/v1/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """管理员通过用户名/密码换取 Bearer token（JWT）。"""
    return await login_for_access_token(form_data)


@app.post("/api/v1/run-auto-hedge-once")
async def run_auto_hedge_once(
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    engine = AutoHedgeEngine(session)
    await engine.run_once()
    return {"status": "ok", "detail": "auto-hedge executed (or simulated)"}


@app.get("/api/v1/ai/state", response_model=AiStateView)
async def get_ai_state(
    session: AsyncSession = Depends(get_session),
    window_days: Optional[int] = Query(
        None, description="窗口期（天），可选，前端可传入以覆盖自动选择"
    ),
    force_refresh: bool = Query(False, description="是否强制刷新缓存"),
    current_user: str = Depends(get_current_user),
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
    print(f"[GET /ai/state] Trade mode: {str(eff.effective_trade_mode)}")

    # Greeks 敞口
    expo_svc = OptionExposureService(session, broker_client)
    expo = await expo_svc.get_account_exposure(account_id)
    print(
        f"[GET /ai/state] Equity: {expo.equity_usd}, Delta: {expo.total_delta_notional_usd}, Gamma: {expo.total_gamma_usd}"
    )

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
    print(
        f"[GET /ai/state] window_days param: {window_days}, using: {effective_window}"
    )

    prof_svc = SymbolRiskProfileService(session)
    behavior_stats = await prof_svc.get_behavior_stats(
        account_id, symbols, effective_window
    )
    print(
        f"[GET /ai/state] Behavior stats retrieved for {len(behavior_stats)} symbols: {list(behavior_stats.keys())}"
    )

    # 计划偏离度（仅针对有计划的标的）
    plan_service = TradingPlanService(session)
    plan_map = await plan_service.get_active_plans_by_symbols(account_id, symbols)
    plan_deviation_map = {}
    if plan_map:
        market_provider = (
            market_data_provider  # 复用全局单例，避免重复创建 Tiger 客户端
        )

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
                plan_deviation_map[sym] = min(
                    abs(price - float(plan.entry_price))
                    / float(plan.entry_price)
                    * 100,
                    100,
                )

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
            if (
                stats.overtrade_score > 70
                and plan_deviation is not None
                and plan_deviation > 30
            ):
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
        trade_mode=str(eff.effective_trade_mode),
        limits=limits_view,
        exposure=exposure_view,
        symbols=symbol_views,
    )

    # 写入缓存（30秒）
    try:
        payload = (
            ai_state.model_dump()
            if hasattr(ai_state, "model_dump")
            else ai_state.dict()
        )
        await cache.set(cache_key, payload, expire=30)
    except Exception:
        pass

    return ai_state


@app.post("/api/v1/ai/advice", response_model=AiAdviceResponse)
async def ai_advice(
    req: AiAdviceRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """AI 决策助手接口。"""
    svc = AiAdviceService(session)
    return await svc.get_advice(req)


@app.get("/api/v1/ai/symbols", response_model=SymbolSearchResponse)
async def search_symbols(
    q: Optional[str] = Query(None, description="搜索关键词"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """模糊搜索美港股标的"""
    svc = AiAdviceService(session)
    return await svc.search_symbols(q or "")


@app.post("/api/v1/ai/analyze-stock", response_model=KlineAnalysisResponse)
async def analyze_stock_kline(
    req: KlineAnalysisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
):
    """多周期K线走势 AI 深度分析"""
    svc = AiAdviceService(session)
    return await svc.analyze_stock_kline(req.symbol)


@app.post("/api/v1/admin/behavior/rebuild")
async def rebuild_behavior_stats(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    async_run: bool = Query(False, description="是否异步执行"),
    current_user: str = Depends(get_current_user),
    t: Callable = Depends(get_translator),
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
            raise HTTPException(status_code=400, detail=t("error.scheduler_disabled"))
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
        return {"status": "ok", "total_jobs": len(jobs), "jobs": jobs}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/v1/admin/scheduler/jobs/{job_id}/pause")
async def pause_scheduled_job(
    job_id: str, current_user: str = Depends(get_current_user)
):
    """暂停指定的定时任务"""
    from app.jobs.scheduler import pause_job

    try:
        pause_job(job_id)
        return {"status": "ok", "message": f"Job {job_id} paused"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/v1/admin/scheduler/jobs/{job_id}/resume")
async def resume_scheduled_job(
    job_id: str, current_user: str = Depends(get_current_user)
):
    """恢复指定的定时任务"""
    from app.jobs.scheduler import resume_job

    try:
        resume_job(job_id)
        return {"status": "ok", "message": f"Job {job_id} resumed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.put("/api/v1/admin/scheduler/jobs/{job_id}/schedule")
async def update_job_schedule(
    job_id: str,
    payload: JobScheduleRequest,
    current_user: str = Depends(get_current_user),
    t: Callable = Depends(get_translator),
):
    """按小时/分钟/时区更新定时任务的触发 cron"""
    from app.jobs.scheduler import format_job, get_job, reschedule_job

    try:
        cron_expr = f"{payload.minute} {payload.hour} * * *"
        reschedule_job(job_id=job_id, cron_expr=cron_expr, timezone=payload.timezone)
        job = get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=404, detail=t("error.job_not_found", id=job_id)
            )
        job_info = format_job(job)
        next_run = job_info.get("next_run_time") if job_info else "soon"
        message = f"Job schedule updated successfully. Next run: {next_run}"
        return {"status": "success", "message": message, "job": job_info}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
