"""潜在机会模块 API 路由"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator

from app.schemas.opportunities import (
    OpportunityLatestResponse,
    OpportunityRunsResponse,
    OpportunityScanRequest,
    OpportunityScanResponse,
    OpportunityRunView,
    OpportunityRunSummaryView,
    OpportunityItemView,
    MacroRiskSnapshot,
)
from app.services.potential_opportunities_service import PotentialOpportunitiesService
from app.services.trading_plan_service import TradingPlanService
from app.core.config import settings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time

from app.models.opportunity_scan import OpportunityScanRun
from app.jobs.scheduler import add_job
from app.jobs.data_refresh_jobs import manual_opportunity_scan_job

router = APIRouter()

BJ_TZ = ZoneInfo("Asia/Shanghai")


# 依赖项：数据库会话（延迟导入避免循环依赖）
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    from app.models.db import SessionLocal
    async with SessionLocal() as session:
        yield session



def _to_macro_snapshot(run) -> MacroRiskSnapshot:
    return MacroRiskSnapshot(
        overall_score=run.macro_overall_score,
        risk_level=run.macro_risk_level,
        risk_summary=run.macro_risk_summary,
    )


def _to_run_view(run, plan_map: dict | None = None) -> OpportunityRunView:
    items = []
    for idx, it in enumerate(run.items or [], start=1):
        plan_match_score = None
        plan_match_reason = None
        if plan_map is not None:
            if it.symbol in plan_map:
                plan_match_score = 1.0
                plan_match_reason = "计划匹配"
            else:
                plan_match_score = 0.0
                plan_match_reason = "未匹配"

        items.append(
            OpportunityItemView(
                rank=idx,
                symbol=it.symbol,
                current_price=it.current_price,
                technical_score=it.technical_score or 0,
                fundamental_score=it.fundamental_score or 0,
                sentiment_score=it.sentiment_score or 0,
                overall_score=it.overall_score or 0,
                recommendation=it.recommendation,
                reason=it.reason,
                plan_match_score=plan_match_score,
                plan_match_reason=plan_match_reason,
            )
        )

    return OpportunityRunView(
        run_id=run.id,
        run_key=run.run_key,
        status=run.status,
        as_of=run.as_of,
        universe_name=run.universe_name,
        min_score=run.min_score,
        max_results=run.max_results,
        force_refresh=bool(run.force_refresh),
        macro_risk=_to_macro_snapshot(run),
        total_symbols=run.total_symbols or 0,
        qualified_symbols=run.qualified_symbols or 0,
        elapsed_ms=run.elapsed_ms,
        items=items,
    )


def _to_run_summary(run) -> OpportunityRunSummaryView:
    return OpportunityRunSummaryView(
        run_id=run.id,
        run_key=run.run_key,
        status=run.status,
        as_of=run.as_of,
        universe_name=run.universe_name,
        min_score=run.min_score,
        max_results=run.max_results,
        total_symbols=run.total_symbols or 0,
        qualified_symbols=run.qualified_symbols or 0,
        elapsed_ms=run.elapsed_ms,
        macro_risk=_to_macro_snapshot(run),
    )


@router.get("/opportunities/latest", response_model=OpportunityLatestResponse)
async def get_latest_opportunities(
    universe_name: str = "US_LARGE_MID_TECH",
    session: AsyncSession = Depends(get_session),
):
    svc = PotentialOpportunitiesService(session)
    latest = await svc.get_latest_success_run(universe_name=universe_name)
    if not latest:
        return OpportunityLatestResponse(status="ok", latest=None)
    plan_service = TradingPlanService(session)
    symbols = [it.symbol for it in latest.items or []]
    plan_map = await plan_service.get_active_plans_by_symbols(settings.TIGER_ACCOUNT, symbols)
    return OpportunityLatestResponse(status="ok", latest=_to_run_view(latest, plan_map))


@router.get("/opportunities/runs", response_model=OpportunityRunsResponse)
async def list_opportunity_runs(
    limit: int = 20,
    universe_name: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    svc = PotentialOpportunitiesService(session)
    runs = await svc.list_runs(limit=limit, universe_name=universe_name)
    return OpportunityRunsResponse(status="ok", runs=[_to_run_summary(r) for r in runs])


@router.get("/opportunities/runs/{run_id}", response_model=OpportunityRunView)
async def get_opportunity_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
):
    svc = PotentialOpportunitiesService(session)
    run = await svc.get_run_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    plan_service = TradingPlanService(session)
    symbols = [it.symbol for it in run.items or []]
    plan_map = await plan_service.get_active_plans_by_symbols(settings.TIGER_ACCOUNT, symbols)
    return _to_run_view(run, plan_map)


@router.post("/opportunities/scan", response_model=OpportunityScanResponse)
async def scan_opportunities(
    req: OpportunityScanRequest,
    session: AsyncSession = Depends(get_session),
):
    # 可选：更新定时任务触发时间（Linux crontab 5 段）
    if req.schedule_cron:
        try:
            from app.jobs.scheduler import reschedule_job, get_job

            job_id = "scan_daily_opportunities_tech"
            reschedule_job(job_id=job_id, cron_expr=req.schedule_cron, timezone=req.schedule_timezone)
            job = get_job(job_id)
            next_run_time = None
            try:
                next_run_time = job.next_run_time.isoformat() if job and job.next_run_time else None
            except Exception:
                next_run_time = None

            # 把调度变更写入 notes（不影响扫描主流程）
            # 注意：notes 由 service 返回；这里先初始化一个占位，稍后 merge。
            schedule_notes = {
                "scheduler": {
                    "job_id": job_id,
                    "cron": req.schedule_cron,
                    "timezone": req.schedule_timezone,
                    "next_run_time": next_run_time,
                }
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid schedule_cron: {e}")
    else:
        schedule_notes = None

    svc = PotentialOpportunitiesService(session)

    # 立即返回：创建一个 SCHEDULED placeholder run，调度一个一键（date）任务让调度器在后台执行真正的扫描。
    as_of_bj = datetime.now(tz=BJ_TZ)
    run_key = svc._build_run_key(as_of_bj, req.universe_name, req.min_score, req.max_results, req.force_refresh)

    # 幂等性检查：如果已存在相同 run_key 的成功扫描，直接返回
    from sqlalchemy import select
    existing_stmt = select(OpportunityScanRun).where(OpportunityScanRun.run_key == run_key)
    existing_run = (await session.execute(existing_stmt)).scalars().first()
    
    if existing_run and existing_run.status == "SUCCESS":
        # 已有成功 run，直接返回（幂等）
        notes = {"idempotent": True, "message": "Same-day scan already exists with SUCCESS status"}
        return OpportunityScanResponse(status="ok", run=_to_run_view(existing_run), notes=notes)

    # 删除已存在的 SCHEDULED/FAILED run（避免 unique constraint 冲突）
    if existing_run:
        await session.delete(existing_run)
        await session.flush()

    placeholder = OpportunityScanRun(
        run_key=run_key,
        as_of=as_of_bj,
        universe_name=req.universe_name,
        min_score=req.min_score,
        max_results=req.max_results,
        force_refresh=1 if req.force_refresh else 0,
        status="SCHEDULED",
        total_symbols=0,
        qualified_symbols=0,
    )

    # 持久化占位 run
    session.add(placeholder)
    await session.commit()
    await session.refresh(placeholder)

    # 调度后台一次性任务（尽量短延迟以避免阻塞当前请求）
    job_id = f"manual_scan_{placeholder.id}_{int(time.time())}"
    run_date = datetime.now(tz=BJ_TZ) + timedelta(seconds=1)

    add_job(
        func=manual_opportunity_scan_job,
        trigger="date",
        id=job_id,
        name="手动潜在机会扫描",
        run_date=run_date,
        args=(req.universe_name, req.min_score, req.max_results, req.force_refresh),
    )

    # 构造返回 notes，包含调度信息及可能的 schedule 更新提示
    notes = {"scheduled_job_id": job_id, "scheduled_run_id": placeholder.id}
    if schedule_notes:
        if "scheduler" not in notes:
            notes.update(schedule_notes)
        else:
            notes["scheduler_update"] = schedule_notes["scheduler"]

    return OpportunityScanResponse(status="ok", run=_to_run_view(placeholder), notes=notes)
