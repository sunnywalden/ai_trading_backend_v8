"""V10.3: 智能订单簿服务"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Any, Optional, overload

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc

from app.models.trading_plan import TradingPlan
from app.models.fsm_transition_log import FsmTransitionLog
from app.schemas.order_book import (
    OrderBookRow, OrderBookGroup, OrderBookResponse, OrderBookSummary,
    OrderBookFilter, RiskBadgeInfo,
    StopLossUpdateResponse,
)
from app.schemas.lifecycle import PIPELINE_STAGE_NAMES

logger = logging.getLogger(__name__)

# ── 分组定义 ──────────────────────────────────────────────────────────────────
GROUP_ACTIVE_STATUSES = {"ACTIVE", "AUTO_EXECUTING", "AI_GENERATED"}
GROUP_MONITORING_STATUSES = {"PENDING_CONFIRM", "EXECUTED"}
GROUP_COMPLETED_STATUSES = {"REVOKED", "FAILED", "CANCELLED", "EXPIRED"}


def _build_risk_badges(plan: TradingPlan, tags: dict) -> list[RiskBadgeInfo]:
    """根据 plan 和 tags 构建风险标志列表。"""
    badges: list[RiskBadgeInfo] = []
    confidence = float(plan.confidence) if plan.confidence else None

    # VAR_HIGH: confidence < 40 且 provenance 中 var_check 未通过
    snapshot = plan.provenance_snapshot or {}
    rg = snapshot.get("risk_gate_results", {})
    if not rg.get("var_check", {}).get("passed", True):
        badges.append(RiskBadgeInfo(type="VAR_HIGH", label="VaR超限", icon="🔒", severity="danger"))

    # FENCE_ACTIVE: tags 中有围栏标记
    if tags.get("earnings_fence_active"):
        badges.append(RiskBadgeInfo(type="FENCE_ACTIVE", label="盈利围栏", icon="🔒", severity="warning"))

    # ALGO_RUNNING: pipeline_stage == 8（算法执行中）
    if plan.pipeline_stage == 8:
        badges.append(RiskBadgeInfo(type="ALGO_RUNNING", label="算法执行中", icon="⚡", severity="info"))

    # LOW_LIQUIDITY: tags 中标记
    if tags.get("low_liquidity"):
        badges.append(RiskBadgeInfo(type="LOW_LIQUIDITY", label="流动性不足", icon="💧", severity="warning"))

    # EXPIRING: valid_until 在 24 小时内
    if plan.valid_until:
        vu = plan.valid_until
        if vu.tzinfo is None:
            vu = vu.replace(tzinfo=timezone.utc)
        if 0 < (vu - datetime.now(timezone.utc)).total_seconds() < 86400:
            badges.append(RiskBadgeInfo(type="EXPIRING", label="即将过期", icon="⏰", severity="warning"))

    # MARGIN_CALL: tags 中标记
    if tags.get("margin_call"):
        badges.append(RiskBadgeInfo(type="MARGIN_CALL", label="追加保证金", icon="📄", severity="danger"))

    return badges


@overload
def _safe_float(val: Any, default: float) -> float: ...


@overload
def _safe_float(val: Any, default: None) -> Optional[float]: ...


@overload
def _safe_float(val: Any) -> float: ...


def _safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """确保 float 值是 JSON 兼容的（处理 NaN/Inf），否则返回 None 或默认值。"""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _plan_to_row(plan: TradingPlan) -> OrderBookRow:
    tags = plan.plan_tags or {}
    badges = _build_risk_badges(plan, tags)

    # 分组
    if plan.plan_status in GROUP_ACTIVE_STATUSES:
        group = "active"
    elif plan.plan_status in GROUP_MONITORING_STATUSES:
        group = "monitoring"
    else:
        group = "completed"

    # AI 摘要截断（80字）
    summary = plan.reasoning or ""
    if len(summary) > 80:
        summary = summary[:77] + "..."

    # entry price range（从 tags 或直接使用 entry_price）
    entry_low = _safe_float(tags.get("entry_price_low"), _safe_float(plan.entry_price))
    entry_high = _safe_float(tags.get("entry_price_high"), _safe_float(plan.entry_price))

    return OrderBookRow(
        plan_id=plan.id,
        account_id=plan.account_id,
        symbol=plan.symbol,
        market=tags.get("market"),
        direction=plan.direction,
        strategy_source=tags.get("strategy_source", plan.plan_type),
        pipeline_stage=plan.pipeline_stage,
        pipeline_stage_name=PIPELINE_STAGE_NAMES.get(plan.pipeline_stage or 16),
        entry_price_target=_safe_float(plan.entry_price),
        entry_price_low=entry_low,
        entry_price_high=entry_high,
        fill_avg_price=_safe_float(tags.get("fill_avg_price"), None),
        stop_loss=_safe_float(plan.stop_loss),
        take_profit=_safe_float(plan.take_profit),
        target_position_pct=float(_safe_float(plan.target_position, 0.0)) * 100 if plan.target_position else None,
        current_position_pct=_safe_float(tags.get("current_position_pct"), None),
        unrealized_pnl=_safe_float(tags.get("unrealized_pnl"), None),
        unrealized_pnl_pct=_safe_float(tags.get("unrealized_pnl_pct"), None),
        confidence=_safe_float(plan.confidence, None),
        six_dim_scores=(plan.provenance_snapshot or {}).get("six_dim_scores"),
        risk_badges=badges,
        ai_summary=summary or None,
        plan_status=plan.plan_status,
        autonomy_action=plan.autonomy_action,
        source=plan.source,
        position_fsm_state=plan.position_fsm_state,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        valid_until=plan.valid_until,
        group=group,
    )


class OrderBookService:

    async def list_orders(
        self,
        db: AsyncSession,
        filters: Optional[OrderBookFilter] = None,
    ) -> OrderBookResponse:
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

        conditions = []

        # 只查当日之后创建 + 当日已完成的（避免历史数据过大）
        conditions.append(
            or_(
                TradingPlan.plan_status.notin_(list(GROUP_COMPLETED_STATUSES)),
                TradingPlan.updated_at >= today_start,
            )
        )

        if filters:
            if filters.direction:
                conditions.append(TradingPlan.direction == filters.direction)
            if filters.account_id:
                conditions.append(TradingPlan.account_id == filters.account_id)
            if filters.plan_type:
                conditions.append(TradingPlan.plan_type == filters.plan_type)
            if filters.stage_min is not None:
                conditions.append(TradingPlan.pipeline_stage >= filters.stage_min)
            if filters.stage_max is not None:
                conditions.append(TradingPlan.pipeline_stage <= filters.stage_max)
            if filters.confidence_min is not None:
                conditions.append(TradingPlan.confidence >= filters.confidence_min)
            if filters.confidence_max is not None:
                conditions.append(TradingPlan.confidence <= filters.confidence_max)
            if filters.date_from:
                conditions.append(TradingPlan.created_at >= filters.date_from)
            if filters.date_to:
                conditions.append(TradingPlan.created_at <= filters.date_to)
            if filters.search:
                conditions.append(TradingPlan.symbol.ilike(f"%{filters.search}%"))

        stmt = (
            select(TradingPlan)
            .where(and_(*conditions))
            .order_by(desc(TradingPlan.updated_at))
            .limit(500)
        )
        result = await db.execute(stmt)
        plans = result.scalars().all()

        rows = [_plan_to_row(p) for p in plans]

        # 分组
        active_rows    = [r for r in rows if r.group == "active"]
        monitoring_rows = [r for r in rows if r.group == "monitoring"]
        completed_rows = [r for r in rows if r.group == "completed"]

        groups = [
            OrderBookGroup(group_id="active",     group_label="活跃执行中", count=len(active_rows),    items=active_rows),
            OrderBookGroup(group_id="monitoring",  group_label="监控中",    count=len(monitoring_rows), items=monitoring_rows),
            OrderBookGroup(group_id="completed",   group_label="今日已完成", count=len(completed_rows), items=completed_rows),
        ]

        return OrderBookResponse(groups=groups, total=len(rows), as_of=now)

    async def get_summary(self, db: AsyncSession) -> OrderBookSummary:
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

        # 活跃数
        active_stmt = select(func.count()).where(TradingPlan.plan_status.in_(list(GROUP_ACTIVE_STATUSES)))
        active_count = (await db.execute(active_stmt)).scalar() or 0

        # 监控数
        monitoring_stmt = select(func.count()).where(TradingPlan.plan_status.in_(list(GROUP_MONITORING_STATUSES)))
        monitoring_count = (await db.execute(monitoring_stmt)).scalar() or 0

        # 今日完成数
        completed_stmt = select(func.count()).where(
            and_(
                TradingPlan.plan_status.in_(list(GROUP_COMPLETED_STATUSES)),
                TradingPlan.updated_at >= today_start,
            )
        )
        completed_count = (await db.execute(completed_stmt)).scalar() or 0

        # 平均置信度
        conf_stmt = select(func.avg(TradingPlan.confidence)).where(
            TradingPlan.plan_status.in_(list(GROUP_ACTIVE_STATUSES))
        )
        avg_conf = (await db.execute(conf_stmt)).scalar()

        # 总浮盈：unrealized_pnl 存储在 plan_tags JSON，从 Python 层累加
        pnl_stmt = select(TradingPlan.plan_tags).where(
            TradingPlan.plan_status.in_(list(GROUP_ACTIVE_STATUSES))
        )
        pnl_rows = (await db.execute(pnl_stmt)).scalars().all()
        total_pnl = sum(
            _safe_float((tags or {}).get("unrealized_pnl"), 0.0)
            for tags in pnl_rows
        )

        # 买卖数量
        buy_stmt = select(func.count()).where(TradingPlan.direction == "BUY")
        sell_stmt = select(func.count()).where(TradingPlan.direction == "SELL")
        buy_count = (await db.execute(buy_stmt)).scalar() or 0
        sell_count = (await db.execute(sell_stmt)).scalar() or 0

        return OrderBookSummary(
            total_active=active_count,
            total_monitoring=monitoring_count,
            total_completed_today=completed_count,
            total_unrealized_pnl=float(_safe_float(total_pnl, 0.0)),
            avg_confidence=round(float(_safe_float(avg_conf, 0.0)), 1) if avg_conf is not None else None,
            buy_count=buy_count,
            sell_count=sell_count,
            as_of=now,
        )

    async def get_order_detail(self, db: AsyncSession, plan_id: int) -> Optional[OrderBookRow]:
        result = await db.execute(select(TradingPlan).where(TradingPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            return None
        return _plan_to_row(plan)

    async def update_stop_loss(
        self,
        db: AsyncSession,
        plan_id: int,
        new_stop_loss: float,
        reason: Optional[str] = None,
    ) -> Optional[StopLossUpdateResponse]:
        result = await db.execute(select(TradingPlan).where(TradingPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            return None

        old_sl = float(plan.stop_loss)
        plan.stop_loss = Decimal(str(new_stop_loss))

        # 写入 FSM 转换日志
        log = FsmTransitionLog(
            plan_id=plan_id,
            fsm_type="PLAN",
            from_state=f"SL={old_sl}",
            to_state=f"SL={new_stop_loss}",
            engine="manual",
            trigger_reason=reason or "手动修改止损",
        )
        db.add(log)
        await db.commit()
        await db.refresh(plan)

        return StopLossUpdateResponse(
            plan_id=plan_id,
            old_stop_loss=old_sl,
            new_stop_loss=new_stop_loss,
            updated_at=plan.updated_at or datetime.now(timezone.utc),
        )


order_book_service = OrderBookService()
