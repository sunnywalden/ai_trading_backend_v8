"""V10.3: 交易生命周期服务

提供 Pipeline 分布、FSM 状态统计、事件流查询、决策溯源组装。
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, true, update

from app.models.trading_plan import TradingPlan
from app.models.fsm_transition_log import FsmTransitionLog
from app.schemas.lifecycle import (
    PipelineDistribution, PipelineStageColumn, PipelineTaskCard,
    PlanFsmSummary, PlanFsmStateCount,
    PositionFsmSummary, PositionFsmStateCount, EngineStats,
    FsmEventPage, FsmTransitionEvent,
    DecisionProvenance, SixDimScore, RiskGateCheck, ExecProgress,
    PIPELINE_STAGE_NAMES, PIPELINE_P50_BENCHMARKS,
    PLAN_FSM_STATES, POSITION_FSM_STATES,
)

logger = logging.getLogger(__name__)

# ── Plan FSM 状态显示配置 ──────────────────────────────────────────────────────
PLAN_FSM_META: dict[str, dict] = {
    "AI_GENERATED":    {"label": "AI已生成",   "color": "#a78bfa"},
    "AUTO_EXECUTING":  {"label": "自动执行中", "color": "#3b82f6"},
    "PENDING_CONFIRM": {"label": "待人工确认", "color": "#f59e0b"},
    "ACTIVE":          {"label": "活跃",       "color": "#10b981"},
    "EXECUTED":        {"label": "已执行",     "color": "#6366f1"},
    "REVOKED":         {"label": "已撤销",     "color": "#ef4444"},
    "FAILED":          {"label": "已失败",     "color": "#ef4444"},
    "CANCELLED":       {"label": "已取消",     "color": "#9ca3af"},
    "EXPIRED":         {"label": "已过期",     "color": "#6b7280"},
}

# ── Position FSM 状态显示配置 ──────────────────────────────────────────────────
POSITION_FSM_META: dict[str, dict] = {
    "ENTERING":       {"label": "建仓中",   "color": "#3b82f6"},
    "HELD":           {"label": "持有中",   "color": "#10b981"},
    "SCALING_IN":     {"label": "加仓中",   "color": "#22d3ee"},
    "SCALING_OUT":    {"label": "减仓中",   "color": "#f97316"},
    "EXITING_FULL":   {"label": "全仓离场", "color": "#ef4444"},
    "STOP_LOSS_EXIT": {"label": "止损离场", "color": "#dc2626"},
    "CLOSED":         {"label": "已关闭",   "color": "#6b7280"},
}


def _derive_position_fsm_state(plan_status: Optional[str], pipeline_stage: Optional[int]) -> str:
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

        # 查询所有未关闭计划（pipeline_stage 不为 None）
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.pipeline_stage.isnot(None),
                TradingPlan.plan_status.notin_(["CANCELLED", "EXPIRED", "FAILED"]),
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

                tasks.append(PipelineTaskCard(
                    plan_id=p.id,
                    symbol=p.symbol,
                    direction=p.direction,
                    confidence=float(p.confidence) if p.confidence else None,
                    source=p.source,
                    stage_entered_at=p.stage_entered_at,
                    seconds_in_stage=secs,
                    delay_level=delay_level,
                ))

            columns.append(PipelineStageColumn(
                stage=stage,
                stage_name=PIPELINE_STAGE_NAMES[stage],
                p50_benchmark=PIPELINE_P50_BENCHMARKS[stage],
                count=len(stage_plans),
                avg_seconds=(total_secs / len(stage_plans)) if stage_plans else None,
                tasks=tasks,
            ))

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
        stmt = select(TradingPlan.plan_status, func.count().label("cnt")).group_by(TradingPlan.plan_status)
        result = await db.execute(stmt)
        rows = {r.plan_status: r.cnt for r in result.all()}

        states: list[PlanFsmStateCount] = []
        total = 0
        for state in PLAN_FSM_STATES:
            meta = PLAN_FSM_META.get(state, {"label": state, "color": "#9ca3af"})
            cnt = rows.get(state, 0)
            total += cnt
            states.append(PlanFsmStateCount(
                state=state, label=meta["label"], count=cnt, color=meta["color"]
            ))

        return PlanFsmSummary(states=states, total=total, as_of=now)

    # ─────────────────────────────────────────────────────────────────────────
    # Position FSM
    # ─────────────────────────────────────────────────────────────────────────
    async def get_position_fsm_counts(self, db: AsyncSession) -> PositionFsmSummary:
        now = datetime.now(timezone.utc)

        # 拉取所有计划（含 position_fsm_state 为 NULL 的），推导状态
        plans_result = await db.execute(
            select(
                TradingPlan.plan_status,
                TradingPlan.pipeline_stage,
                TradingPlan.position_fsm_state,
            )
        )
        rows: dict[str, int] = {}
        for p in plans_result.all():
            # 优先用存储值，否则推导
            state = p.position_fsm_state or _derive_position_fsm_state(
                p.plan_status, p.pipeline_stage
            )
            rows[state] = rows.get(state, 0) + 1

        states: list[PositionFsmStateCount] = []
        total = 0
        for state in POSITION_FSM_STATES:
            meta = POSITION_FSM_META.get(state, {"label": state, "color": "#9ca3af"})
            cnt = rows.get(state, 0)
            total += cnt
            states.append(PositionFsmStateCount(
                state=state, label=meta["label"], count=cnt, color=meta["color"]
            ))

        # 引擎触发统计
        engine_stmt = select(
            FsmTransitionLog.engine,
            func.count().label("cnt")
        ).where(
            and_(
                FsmTransitionLog.fsm_type == "POSITION",
                FsmTransitionLog.engine.isnot(None),
            )
        ).group_by(FsmTransitionLog.engine)
        engine_result = await db.execute(engine_stmt)
        engine_rows = {r.engine: r.cnt for r in engine_result.all()}

        engine_stats = EngineStats(
            scale_in_count=engine_rows.get("scale_in", 0),
            scale_out_count=engine_rows.get("scale_out", 0),
            trailing_stop_count=engine_rows.get("trailing", 0),
            total_triggers=sum(engine_rows.values()),
        )

        return PositionFsmSummary(states=states, engine_stats=engine_stats, total=total, as_of=now)

    async def sync_position_fsm_states(self, db: AsyncSession) -> int:
        """批量将 position_fsm_state IS NULL 的计划按推导规则回写入库。

        返回更新的行数。由 post_trade_pipeline_service / 定时任务调用。
        """
        plans = (
            await db.execute(
                select(TradingPlan).where(TradingPlan.position_fsm_state.is_(None))
            )
        ).scalars().all()

        updated = 0
        for plan in plans:
            derived = _derive_position_fsm_state(plan.plan_status, plan.pipeline_stage)
            plan.position_fsm_state = derived
            updated += 1

        if updated:
            await db.flush()
            logger.info("[LifecycleService] sync_position_fsm_states: updated %d plans", updated)
        return updated

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
        conditions = []
        if fsm_type:
            conditions.append(FsmTransitionLog.fsm_type == fsm_type.upper())

        # Total count
        count_stmt = select(func.count()).select_from(FsmTransitionLog)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await db.execute(count_stmt)).scalar() or 0

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
            items.append(FsmTransitionEvent(
                id=log.id,
                plan_id=log.plan_id,
                symbol=symbol,
                fsm_type=log.fsm_type,
                from_state=log.from_state,
                to_state=log.to_state,
                engine=log.engine,
                qty_delta=self._clean_float(log.qty_delta) if log.qty_delta is not None else None,
                trigger_reason=log.trigger_reason,
                occurred_at=log.occurred_at,
            ))

        return FsmEventPage(items=items, total=total, page=page, size=size)

    # ─────────────────────────────────────────────────────────────────────────
    # Decision Provenance
    # ─────────────────────────────────────────────────────────────────────────
    async def get_provenance(self, db: AsyncSession, plan_id: int) -> Optional[DecisionProvenance]:
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
            "technical":    "技术面",
            "fundamental":  "基本面",
            "macro":        "宏观",
            "volatility":   "波动率",
            "options":      "期权流",
            "sentiment":    "情绪面",
        }
        dim_weights = {
            "technical": 0.25, "fundamental": 0.20, "macro": 0.15,
            "volatility": 0.15, "options": 0.15, "sentiment": 0.10,
        }
        for dim, label in dim_labels.items():
            if dim in raw_scores:
                raw = self._clean_float(raw_scores[dim].get("score", 0))
                multiplier = self._clean_float(raw_scores[dim].get("regime_multiplier", 1.0), 1.0)
                contribution = raw * multiplier * dim_weights.get(dim, 0)
                
                total_contributions = sum(
                    self._clean_float(raw_scores[d].get("score", 0)) * 
                    self._clean_float(raw_scores[d].get("regime_multiplier", 1.0), 1.0) * 
                    dim_weights.get(d, 0)
                    for d in raw_scores
                )
                if math.isnan(total_contributions) or total_contributions == 0:
                    total_contributions = 1.0
                
                six_dim_scores.append(SixDimScore(
                    dimension=dim,
                    label=label,
                    raw_score=raw,
                    regime_multiplier=multiplier,
                    weighted_contribution=round(self._clean_float(contribution), 3),
                    contribution_pct=round(self._clean_float(contribution / total_contributions * 100), 1),
                ))

        # ② 风险门控
        rg_results = snapshot.get("risk_gate_results", {})
        check_labels = {
            "var_check":             "VaR@95%",
            "stress_test":           "压力测试",
            "position_compliance":   "仓位合规",
            "frequency_check":       "频率检查",
            "circuit_breaker":       "熔断检查",
        }
        for check_key, check_label in check_labels.items():
            if check_key in rg_results:
                six = rg_results[check_key]
                risk_gate_checks.append(RiskGateCheck(
                    check_name=check_key,
                    label=check_label,
                    passed=six.get("passed", True),
                    detail=six.get("reason"),
                ))

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
                avg_fill_price=self._clean_float(exec_data.get("avg_fill_price")) if exec_data.get("avg_fill_price") is not None else None,
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
            confidence=self._clean_float(plan.confidence, 0.0) if plan.confidence is not None else None,
            autonomy_action=plan.autonomy_action,
        )


lifecycle_service = LifecycleService()
