"""V10.3: 交易生命周期服务

提供 Pipeline 分布、FSM 状态统计、事件流查询、决策溯源组装。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan
from app.schemas.lifecycle import (
    PIPELINE_P50_BENCHMARKS,
    PIPELINE_STAGE_NAMES,
    PLAN_FSM_STATES,
    POSITION_FSM_STATES,
    DecisionProvenance,
    EngineStats,
    ExecProgress,
    FsmEventPage,
    FsmTransitionEvent,
    PipelineDistribution,
    PipelineStageColumn,
    PipelineTaskCard,
    PlanFsmStateCount,
    PlanFsmSummary,
    PositionBoard,
    PositionBoardCard,
    PositionBoardColumn,
    PositionFsmStateCount,
    PositionFsmSummary,
    RiskGateCheck,
    SixDimScore,
)

logger = logging.getLogger(__name__)

_OPERATIONAL_PLAN_STATUSES = frozenset(
    {
        "AI_GENERATED",
        "AUTO_EXECUTING",
        "PENDING_CONFIRM",
        "ACTIVE",
    }
)
# EXECUTED 状态只要 pipeline_stage < 16 就视为仍在流水线中（含 S7 下单执行中）
_EXECUTED_ACTIVE_STAGES = frozenset({7, 8, 9, 10, 11, 12, 13, 14, 15})

# ── Plan FSM 状态显示配置 ──────────────────────────────────────────────────────
PLAN_FSM_META: dict[str, dict] = {
    "AI_GENERATED": {"label": "AI已生成", "color": "#a78bfa"},
    "AUTO_EXECUTING": {"label": "自动执行中", "color": "#3b82f6"},
    "PENDING_CONFIRM": {"label": "待人工确认", "color": "#f59e0b"},
    "ACTIVE": {"label": "活跃", "color": "#10b981"},
    "EXECUTED": {"label": "已执行", "color": "#6366f1"},
    "REVOKED": {"label": "已撤销", "color": "#ef4444"},
    "FAILED": {"label": "已失败", "color": "#ef4444"},
    "CANCELLED": {"label": "已取消", "color": "#9ca3af"},
    "EXPIRED": {"label": "已过期", "color": "#6b7280"},
}

# ── Position FSM 状态显示配置 ──────────────────────────────────────────────────
POSITION_FSM_META: dict[str, dict] = {
    "PENDING": {"label": "待确认", "color": "#9ca3af"},
    "OPENING": {"label": "建仓中", "color": "#3b82f6"},
    "ACTIVE": {"label": "持有中", "color": "#10b981"},
    "SCALING_IN": {"label": "加仓中", "color": "#22d3ee"},
    "SCALING_OUT": {"label": "减仓中", "color": "#f97316"},
    "PARTIALLY_CLOSED": {"label": "部分平仓", "color": "#eab308"},
    "CLOSING": {"label": "平仓中", "color": "#ef4444"},
    "EXCEPTION": {"label": "异常(需干预)", "color": "#b91c1c"},
    "LIQUIDATED": {"label": "强制清算", "color": "#7f1d1d"},
    "CLOSED": {"label": "已离场", "color": "#6b7280"},
}


def _derive_position_fsm_state(
    plan_status: Optional[str], pipeline_stage: Optional[int]
) -> str:
    """从 plan_status + pipeline_stage 推导持仓 FSM 状态。

    用于 position_fsm_state 字段为 NULL 时的回退逻辑。
    优先级：pipeline_stage > plan_status。
    """
    s = pipeline_stage or 0
    ps = plan_status or ""

    # 已终结状态
    if ps in ("REVOKED", "FAILED", "CANCELLED", "EXPIRED") or s >= 12:
        return "CLOSED"

    # 进入执行阶段（下单/算法执行中） → 建仓中
    if s in (7, 8):
        return "ENTERING"

    # 持仓监控 → 持有中
    if s == 9:
        return "HELD"

    # 仓位调整 → 加仓或减仓，默认 SCALING_IN（无法精确区分时取加仓）
    if s == 10:
        return "SCALING_IN"

    # 离场触发 → 全仓离场
    if s == 11:
        return "EXITING_FULL"

    # 信号/计划已执行但无精确阶段 → 持有中
    if ps == "EXECUTED":
        return "HELD"

    # 活跃中（待执行）→ 建仓中
    if ps in ("ACTIVE", "AUTO_EXECUTING", "AI_GENERATED", "PENDING_CONFIRM"):
        return "ENTERING"

    return "HELD"  # 兜底


def _make_position_snapshot_event(
    plan: TradingPlan, occurred_at: datetime, event_id: int
) -> FsmTransitionEvent:
    current_state = plan.position_fsm_state or _derive_position_fsm_state(
        plan.plan_status, plan.pipeline_stage
    )
    return FsmTransitionEvent(
        id=event_id,
        plan_id=plan.id,
        symbol=plan.symbol,
        fsm_type="POSITION",
        from_state=None,
        to_state=current_state,
        engine="snapshot",
        qty_delta=None,
        trigger_reason="Current position FSM snapshot (historical POSITION logs unavailable)",
        occurred_at=occurred_at,
    )


class LifecycleService:

    def _clean_float(self, val: Any, default: float = 0.0) -> float:
        """确保 float 值是 JSON 兼容的（处理 NaN/Inf）。"""
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (TypeError, ValueError):
            return default

    # ─────────────────────────────────────────────────────────────────────────
    # Pipeline Distribution
    # ─────────────────────────────────────────────────────────────────────────
    async def get_pipeline_distribution(self, db: AsyncSession) -> PipelineDistribution:
        """查询当前各 Pipeline 阶段的任务分布。"""
        now = datetime.now(timezone.utc)

        # 仅统计“仍在运行中的流水线”计划，避免历史终态/脏数据污染系统监控。
        # - AI_GENERATED / AUTO_EXECUTING / PENDING_CONFIRM / ACTIVE：天然属于活跃链路
        # - EXECUTED：只要仍停留在 S7-S15，就说明仍在执行/持仓/后处理链路中
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.pipeline_stage.isnot(None),
                TradingPlan.pipeline_stage < 16,
                (
                    TradingPlan.plan_status.in_(tuple(_OPERATIONAL_PLAN_STATUSES))
                    | and_(
                        TradingPlan.plan_status == "EXECUTED",
                        TradingPlan.pipeline_stage.in_(tuple(_EXECUTED_ACTIVE_STAGES)),
                    )
                ),
            )
        )
        result = await db.execute(stmt)
        plans = result.scalars().all()

        # 按 stage 分组
        stage_map: dict[int, list[TradingPlan]] = {}
        for plan in plans:
            s = plan.pipeline_stage or 0
            stage_map.setdefault(s, []).append(plan)

        columns: list[PipelineStageColumn] = []
        for stage in range(17):
            stage_plans = stage_map.get(stage, [])
            tasks: list[PipelineTaskCard] = []
            total_secs = 0
            for p in stage_plans:
                secs = None
                if p.stage_entered_at:
                    entered = p.stage_entered_at
                    if entered.tzinfo is None:
                        entered = entered.replace(tzinfo=timezone.utc)
                    secs = int((now - entered).total_seconds())
                    total_secs += secs

                # 计算延迟等级
                p50 = PIPELINE_P50_BENCHMARKS.get(stage)
                delay_level = "green"
                if secs is not None and p50 is not None:
                    if secs > p50 * 3:
                        delay_level = "red"
                    elif secs > p50 * 1.5:
                        delay_level = "yellow"
                elif p.plan_status in ("REVOKED", "FAILED", "CANCELLED"):
                    delay_level = "stopped"

                tasks.append(
                    PipelineTaskCard(
                        plan_id=p.id,
                        symbol=p.symbol,
                        direction=p.direction,
                        confidence=float(p.confidence) if p.confidence else None,
                        source=p.source,
                        stage_entered_at=p.stage_entered_at,
                        seconds_in_stage=secs,
                        delay_level=delay_level,
                    )
                )

            columns.append(
                PipelineStageColumn(
                    stage=stage,
                    stage_name=PIPELINE_STAGE_NAMES[stage],
                    p50_benchmark=PIPELINE_P50_BENCHMARKS[stage],
                    count=len(stage_plans),
                    avg_seconds=(
                        (total_secs / len(stage_plans)) if stage_plans else None
                    ),
                    tasks=tasks,
                )
            )

        return PipelineDistribution(
            columns=columns,
            total_active=len(plans),
            as_of=now,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Plan FSM
    # ─────────────────────────────────────────────────────────────────────────
    async def get_plan_fsm_counts(self, db: AsyncSession) -> PlanFsmSummary:
        now = datetime.now(timezone.utc)
        stmt = select(TradingPlan.plan_status, func.count().label("cnt")).group_by(
            TradingPlan.plan_status
        )
        result = await db.execute(stmt)
        rows = {r.plan_status: r.cnt for r in result.all()}

        states: list[PlanFsmStateCount] = []
        total = 0
        for state in PLAN_FSM_STATES:
            meta = PLAN_FSM_META.get(state, {"label": state, "color": "#9ca3af"})
            cnt = rows.get(state, 0)
            total += cnt
            states.append(
                PlanFsmStateCount(
                    state=state, label=meta["label"], count=cnt, color=meta["color"]
                )
            )

        return PlanFsmSummary(states=states, total=total, as_of=now)

    # ─────────────────────────────────────────────────────────────────────────
    # Position FSM
    # ─────────────────────────────────────────────────────────────────────────
    async def get_position_board(self, db: AsyncSession) -> PositionBoard:
        """Return position-lifecycle kanban grouped by position status.

        Active states (PENDING … EXCEPTION) show all records.
        CLOSED / LIQUIDATED show only records closed in the past 90 days so
        recently-closed positions (e.g. capacity-guard exits) remain visible
        without polluting the board with ancient history.
        """
        now = datetime.now(timezone.utc)

        # Import Position model
        from app.models.position import Position

        # For terminal states we only load the last 90 days to keep the board tidy.
        _90d_ago = now - timedelta(days=90)

        stmt = select(Position).where(
            and_(
                Position.symbol.isnot(None),
                # Include every non-terminal record + terminal records within 90d
                (
                    Position.status.notin_(("CLOSED", "LIQUIDATED"))
                    | (Position.closed_at >= _90d_ago)
                    | (Position.updated_at >= _90d_ago)
                ),
            )
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        # Group by status
        state_map: dict[str, list[PositionBoardCard]] = {
            s: [] for s in POSITION_FSM_STATES
        }

        for r in rows:
            state = r.status
            if state not in state_map:
                state_map[state] = []

            hold_secs: Optional[int] = None
            if r.updated_at:
                entered = r.updated_at
                if entered.tzinfo is None:
                    entered = entered.replace(tzinfo=timezone.utc)
                hold_secs = int((now - entered).total_seconds())

            state_map[state].append(
                PositionBoardCard(
                    id=r.id,
                    symbol=r.symbol,
                    direction=r.direction,
                    total_qty=float(r.total_qty) if r.total_qty is not None else 0.0,
                    avg_entry_price=(
                        float(r.avg_entry_price)
                        if r.avg_entry_price is not None
                        else None
                    ),
                    unrealized_pnl_pct=(
                        float(r.unrealized_pnl_pct)
                        if r.unrealized_pnl_pct is not None
                        else None
                    ),
                    hold_seconds=hold_secs,
                    latest_plan_id=r.latest_plan_id,
                )
            )

        # Build columns: all states including CLOSED / LIQUIDATED
        columns: list[PositionBoardColumn] = []
        total_active = 0
        for state in POSITION_FSM_STATES:
            meta = POSITION_FSM_META.get(state, {"label": state, "color": "#9ca3af"})
            cards = state_map.get(state, [])
            is_terminal = state in ("CLOSED", "LIQUIDATED")
            if not is_terminal:
                total_active += len(cards)
            # Skip empty terminal columns to avoid clutter when there's no history
            if is_terminal and not cards:
                continue
            columns.append(
                PositionBoardColumn(
                    state=state,
                    label=meta["label"],
                    color=meta["color"],
                    count=len(cards),
                    cards=cards,
                )
            )

        return PositionBoard(columns=columns, total_active=total_active, as_of=now)

    async def get_position_fsm_counts(self, db: AsyncSession) -> PositionFsmSummary:
        now = datetime.now(timezone.utc)

        from app.models.position import Position

        stmt = select(Position.status, func.count().label("cnt")).group_by(
            Position.status
        )
        result = await db.execute(stmt)
        rows_db = result.all()
        rows = {r.status: r.cnt for r in rows_db}

        states: list[PositionFsmStateCount] = []
        total = 0
        for state in POSITION_FSM_STATES:
            meta = POSITION_FSM_META.get(state, {"label": state, "color": "#9ca3af"})
            cnt = rows.get(state, 0)
            if state not in ("CLOSED", "LIQUIDATED"):
                total += cnt
            states.append(
                PositionFsmStateCount(
                    state=state, label=meta["label"], count=cnt, color=meta["color"]
                )
            )

        # 引擎触发统计
        engine_stmt = (
            select(FsmTransitionLog.engine, func.count().label("cnt"))
            .where(
                and_(
                    FsmTransitionLog.fsm_type == "POSITION",
                    FsmTransitionLog.engine.isnot(None),
                )
            )
            .group_by(FsmTransitionLog.engine)
        )
        engine_result = await db.execute(engine_stmt)
        engine_rows = {r.engine: r.cnt for r in engine_result.all()}

        engine_stats = EngineStats(
            scale_in_count=engine_rows.get("scale_in", 0),
            scale_out_count=engine_rows.get("scale_out", 0),
            trailing_stop_count=engine_rows.get("trailing", 0),
            total_triggers=sum(engine_rows.values()),
        )

        return PositionFsmSummary(
            states=states, engine_stats=engine_stats, total=total, as_of=now
        )

    async def sync_position_fsm_states(self, db: AsyncSession) -> int:
        """批量将 position_fsm_state IS NULL 的计划按推导规则回写入库。

        返回更新的行数。由 post_trade_pipeline_service / 定时任务调用。
        """
        plans = (
            (
                await db.execute(
                    select(TradingPlan).where(TradingPlan.position_fsm_state.is_(None))
                )
            )
            .scalars()
            .all()
        )

        updated = 0
        for plan in plans:
            derived = _derive_position_fsm_state(plan.plan_status, plan.pipeline_stage)
            plan.position_fsm_state = derived
            updated += 1

        if updated:
            await db.flush()
            logger.info(
                "[LifecycleService] sync_position_fsm_states: updated %d plans", updated
            )
        return updated

    async def append_position_fsm_log(
        self,
        db: AsyncSession,
        *,
        plan_id: int,
        from_state: Optional[str],
        to_state: Optional[str],
        engine: Optional[str] = None,
        trigger_reason: Optional[str] = None,
    ) -> None:
        if not to_state or from_state == to_state:
            return
        db.add(
            FsmTransitionLog(
                plan_id=plan_id,
                fsm_type="POSITION",
                from_state=from_state,
                to_state=to_state,
                engine=engine,
                trigger_reason=trigger_reason,
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # FSM Events
    # ─────────────────────────────────────────────────────────────────────────
    async def get_fsm_events(
        self,
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        fsm_type: Optional[str] = None,
    ) -> FsmEventPage:
        normalized_fsm_type = fsm_type.upper() if fsm_type else None
        conditions = []
        if normalized_fsm_type:
            conditions.append(FsmTransitionLog.fsm_type == normalized_fsm_type)

        # Total count
        count_stmt = select(func.count()).select_from(FsmTransitionLog)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await db.execute(count_stmt)).scalar() or 0

        # POSITION 事件历史尚未完整沉淀时，提供当前持仓 FSM 快照兜底，避免前端空白。
        if normalized_fsm_type == "POSITION" and total == 0:
            plans = list(
                (
                    await db.execute(
                        select(TradingPlan)
                        .where(TradingPlan.position_fsm_state.is_not(None))
                        .order_by(desc(TradingPlan.updated_at), desc(TradingPlan.id))
                        .limit(size)
                        .offset((page - 1) * size)
                    )
                )
                .scalars()
                .all()
            )

            snapshot_items: list[FsmTransitionEvent] = []
            for idx, plan in enumerate(plans, start=1):
                occurred_at = (
                    plan.updated_at or plan.created_at or datetime.now(timezone.utc)
                )
                if occurred_at.tzinfo is None:
                    occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                snapshot_items.append(
                    _make_position_snapshot_event(
                        plan, occurred_at, event_id=-(page * 100000 + idx)
                    )
                )

            snapshot_total = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(TradingPlan)
                        .where(TradingPlan.position_fsm_state.is_not(None))
                    )
                ).scalar()
                or 0
            )
            return FsmEventPage(
                items=snapshot_items, total=snapshot_total, page=page, size=size
            )

        # Fetch items with symbol join
        stmt = (
            select(FsmTransitionLog, TradingPlan.symbol)
            .outerjoin(TradingPlan, TradingPlan.id == FsmTransitionLog.plan_id)
            .where(and_(*conditions) if conditions else true())
            .order_by(desc(FsmTransitionLog.occurred_at))
            .limit(size)
            .offset((page - 1) * size)
        )
        result = await db.execute(stmt)

        items: list[FsmTransitionEvent] = []
        for log, symbol in result.all():
            items.append(
                FsmTransitionEvent(
                    id=log.id,
                    plan_id=log.plan_id,
                    symbol=symbol,
                    fsm_type=log.fsm_type,
                    from_state=log.from_state,
                    to_state=log.to_state,
                    engine=log.engine,
                    qty_delta=(
                        self._clean_float(log.qty_delta)
                        if log.qty_delta is not None
                        else None
                    ),
                    trigger_reason=log.trigger_reason,
                    occurred_at=log.occurred_at,
                )
            )

        return FsmEventPage(items=items, total=total, page=page, size=size)

    # ─────────────────────────────────────────────────────────────────────────
    # Decision Provenance
    # ─────────────────────────────────────────────────────────────────────────
    async def get_provenance(
        self, db: AsyncSession, plan_id: int
    ) -> Optional[DecisionProvenance]:
        """组装单笔交易决策溯源链（5 卡片）。"""
        result = await db.execute(select(TradingPlan).where(TradingPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            return None

        # ① 六维信号分数（从 provenance_snapshot 取）
        six_dim_scores: list[SixDimScore] = []
        risk_gate_checks: list[RiskGateCheck] = []
        exec_progress: Optional[ExecProgress] = None
        regime: Optional[str] = None

        snapshot = plan.provenance_snapshot or {}

        raw_scores = snapshot.get("six_dim_scores", {})
        dim_labels = {
            "technical": "技术面",
            "fundamental": "基本面",
            "macro": "宏观",
            "volatility": "波动率",
            "options": "期权流",
            "sentiment": "情绪面",
        }
        dim_weights = {
            "technical": 0.25,
            "fundamental": 0.20,
            "macro": 0.15,
            "volatility": 0.15,
            "options": 0.15,
            "sentiment": 0.10,
        }
        for dim, label in dim_labels.items():
            if dim in raw_scores:
                raw = self._clean_float(raw_scores[dim].get("score", 0))
                multiplier = self._clean_float(
                    raw_scores[dim].get("regime_multiplier", 1.0), 1.0
                )
                contribution = raw * multiplier * dim_weights.get(dim, 0)

                total_contributions = sum(
                    self._clean_float(raw_scores[d].get("score", 0))
                    * self._clean_float(
                        raw_scores[d].get("regime_multiplier", 1.0), 1.0
                    )
                    * dim_weights.get(d, 0)
                    for d in raw_scores
                )
                if math.isnan(total_contributions) or total_contributions == 0:
                    total_contributions = 1.0

                six_dim_scores.append(
                    SixDimScore(
                        dimension=dim,
                        label=label,
                        raw_score=raw,
                        regime_multiplier=multiplier,
                        weighted_contribution=round(self._clean_float(contribution), 3),
                        contribution_pct=round(
                            self._clean_float(contribution / total_contributions * 100),
                            1,
                        ),
                    )
                )

        # ② 风险门控
        rg_results = snapshot.get("risk_gate_results", {})
        check_labels = {
            "var_check": "VaR@95%",
            "stress_test": "压力测试",
            "position_compliance": "仓位合规",
            "frequency_check": "频率检查",
            "circuit_breaker": "熔断检查",
        }
        for check_key, check_label in check_labels.items():
            if check_key in rg_results:
                six = rg_results[check_key]
                risk_gate_checks.append(
                    RiskGateCheck(
                        check_name=check_key,
                        label=check_label,
                        passed=six.get("passed", True),
                        detail=six.get("reason"),
                    )
                )

        # ③ Regime
        regime = snapshot.get("regime")

        # ④ 算法执行进度
        exec_data = snapshot.get("exec_progress")
        if exec_data:
            exec_progress = ExecProgress(
                algo_type=exec_data.get("algo_type"),
                total_slices=int(exec_data.get("total_slices", 0)),
                filled_slices=int(exec_data.get("filled_slices", 0)),
                fill_pct=self._clean_float(exec_data.get("fill_pct", 0.0)),
                avg_fill_price=(
                    self._clean_float(exec_data.get("avg_fill_price"))
                    if exec_data.get("avg_fill_price") is not None
                    else None
                ),
            )

        return DecisionProvenance(
            plan_id=plan.id,
            symbol=plan.symbol,
            direction=plan.direction,
            created_at=plan.created_at,
            six_dim_scores=six_dim_scores,
            risk_gate_checks=risk_gate_checks,
            ai_reasoning=plan.reasoning,
            exec_progress=exec_progress,
            position_fsm_state=plan.position_fsm_state,
            regime=regime,
            confidence=(
                self._clean_float(plan.confidence, 0.0)
                if plan.confidence is not None
                else None
            ),
            autonomy_action=plan.autonomy_action,
        )


lifecycle_service = LifecycleService()
