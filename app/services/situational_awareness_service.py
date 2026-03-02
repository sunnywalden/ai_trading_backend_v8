"""V10.3: 全局态势感知服务

聚合 6 个数据块并提供 WebSocket 推送变更检测。
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.trading_plan import TradingPlan
from app.models.market_regime import MarketRegime
from app.schemas.situational_awareness import (
    SituationalAwarenessSnapshot,
    RegimeBlock, VarBlock, ActiveFencesBlock, ActiveFenceEntry,
    ActiveExecutionsBlock, ActiveExecutionEntry,
    PendingConfirmsBlock, AutonomyBlock,
)

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default

# ── Regime 显示配置 ────────────────────────────────────────────────────────────
REGIME_META: dict[str, dict] = {
    "BULL_TREND":   {"label": "牛市趋势",   "color": "#10b981", "trend": "up"},
    "BEAR_TREND":   {"label": "熊市趋势",   "color": "#ef4444", "trend": "down"},
    "HIGH_VOL":     {"label": "高波动",     "color": "#f59e0b", "trend": "flat"},
    "MEAN_REVERT":  {"label": "均值回归",   "color": "#6366f1", "trend": "flat"},
    "RANGE_BOUND":  {"label": "区间震荡",   "color": "#8b5cf6", "trend": "flat"},
    "CRISIS":       {"label": "危机模式",   "color": "#dc2626", "trend": "down"},
}

# ── Autonomy 显示配置 ─────────────────────────────────────────────────────────
AUTONOMY_META: dict[str, dict] = {
    "FULL":     {"label": "全自主", "color": "#10b981"},
    "SEMI":     {"label": "半自主", "color": "#3b82f6"},
    "ADVISORY": {"label": "建议",   "color": "#8b5cf6"},
}

# ── VaR 限制（%） ─────────────────────────────────────────────────────────────
VAR_LIMIT_PCT = 2.0


class SituationalAwarenessService:

    async def get_snapshot(self, db: AsyncSession) -> SituationalAwarenessSnapshot:
        now = datetime.now(timezone.utc)

        regime_block    = await self._get_regime_block(db)
        var_block       = await self._get_var_block(db)
        fences_block    = await self._get_fences_block(db)
        executions_block = await self._get_executions_block(db)
        confirms_block  = await self._get_confirms_block(db)
        autonomy_block  = await self._get_autonomy_block()

        return SituationalAwarenessSnapshot(
            regime=regime_block,
            var=var_block,
            active_fences=fences_block,
            active_executions=executions_block,
            pending_confirms=confirms_block,
            autonomy=autonomy_block,
            as_of=now,
        )

    # ─────────────────────────────────────────────────────────────────────────
    async def _get_regime_block(self, db: AsyncSession) -> RegimeBlock:
        try:
            stmt = select(MarketRegime).order_by(MarketRegime.classification_date.desc()).limit(1)
            result = await db.execute(stmt)
            regime_obj = result.scalar_one_or_none()
            if not regime_obj:
                return RegimeBlock()

            # regime_obj.regime is typed as str (Enum value stored in DB)
            rtype = str(regime_obj.regime)
            meta = REGIME_META.get(rtype, {"label": rtype, "color": "#6b7280", "trend": "flat"})
            
            # 使用 _safe_float 确保 JSON 合规 (解决 nan 问题)
            raw_conf = _safe_float(regime_obj.confidence, 0.0)
            conf_display = round(raw_conf * 100, 1) if raw_conf <= 1.0 else round(raw_conf, 1)

            return RegimeBlock(
                regime_type=rtype,
                regime_label=meta["label"],
                confidence=conf_display,
                trend_direction=meta["trend"],
                color=meta["color"],
            )
        except Exception as e:
            logger.warning(f"[SA] Failed to get regime block: {e}")
            return RegimeBlock()

    async def _get_var_block(self, db: AsyncSession) -> VarBlock:
        """从 Redis 或 plan_tags 估算当前组合 VaR%。
        简化实现：统计已执行计划的 target_position 之和作为代理指标。
        """
        try:
            stmt = select(func.sum(TradingPlan.target_position)).where(
                TradingPlan.plan_status.in_(["ACTIVE", "AUTO_EXECUTING", "EXECUTED"])
            )
            total_pos = (await db.execute(stmt)).scalar() or 0
            # 粗略：每1%仓位对应约0.1%的VaR（仅示意）
            current_pct = _safe_float(min(float(total_pos) * 0.1, 5.0))
            usage_ratio = current_pct / VAR_LIMIT_PCT if VAR_LIMIT_PCT > 0 else 0

            if usage_ratio >= 1.0:
                level = "red"
            elif usage_ratio >= 0.8:
                level = "yellow"
            else:
                level = "green"

            return VarBlock(
                current_pct=round(current_pct, 2),
                limit_pct=VAR_LIMIT_PCT,
                usage_ratio=round(usage_ratio, 3),
                level=level,
            )
        except Exception as e:
            logger.warning(f"[SA] Failed to get var block: {e}")
            return VarBlock()

    async def _get_fences_block(self, db: AsyncSession) -> ActiveFencesBlock:
        """查询具有盈利围栏的活跃计划。"""
        try:
            # fence_applied 在 event_calendar_entries 中；通过 plan_tags 也有标记
            stmt = select(TradingPlan).where(
                and_(
                    TradingPlan.plan_status.in_(["ACTIVE", "AUTO_EXECUTING"]),
                    # 通过 plan_tags JSON 查找（SQLite/MySQL 均支持 JSON_CONTAINS 方式）
                )
            ).limit(20)
            result = await db.execute(stmt)
            plans = result.scalars().all()

            entries: list[ActiveFenceEntry] = []
            for p in plans:
                tags = p.plan_tags or {}
                if tags.get("earnings_fence_active"):
                    entries.append(ActiveFenceEntry(
                        symbol=p.symbol,
                        fence_type="EARNINGS",
                        expires_at=p.valid_until,
                    ))

            return ActiveFencesBlock(count=len(entries), entries=entries[:5])
        except Exception as e:
            logger.warning(f"[SA] Failed to get fences block: {e}")
            return ActiveFencesBlock()

    async def _get_executions_block(self, db: AsyncSession) -> ActiveExecutionsBlock:
        """查询当前处于算法执行阶段（pipeline_stage == 8）的计划。"""
        try:
            stmt = select(TradingPlan).where(
                TradingPlan.pipeline_stage == 8
            ).limit(10)
            result = await db.execute(stmt)
            plans = result.scalars().all()

            entries: list[ActiveExecutionEntry] = []
            for p in plans:
                tags = p.plan_tags or {}
                snapshot = p.provenance_snapshot or {}
                ep = snapshot.get("exec_progress", {})
                entries.append(ActiveExecutionEntry(
                    plan_id=p.id,
                    symbol=p.symbol,
                    algo_type=tags.get("algo_type", ep.get("algo_type", "TWAP")),
                    fill_pct=_safe_float(ep.get("fill_pct", 0.0)),
                ))

            return ActiveExecutionsBlock(count=len(entries), entries=entries)
        except Exception as e:
            logger.warning(f"[SA] Failed to get executions block: {e}")
            return ActiveExecutionsBlock()

    async def _get_confirms_block(self, db: AsyncSession) -> PendingConfirmsBlock:
        """查询 PENDING_CONFIRM 状态的计划数量。"""
        try:
            stmt = select(TradingPlan).where(
                TradingPlan.plan_status == "PENDING_CONFIRM"
            ).order_by(TradingPlan.created_at.desc()).limit(5)
            result = await db.execute(stmt)
            plans = result.scalars().all()

            count = len(plans)
            symbols = list({p.symbol for p in plans})[:3]

            return PendingConfirmsBlock(
                count=count,
                symbols=symbols,
                is_flashing=count > 0,
            )
        except Exception as e:
            logger.warning(f"[SA] Failed to get confirms block: {e}")
            return PendingConfirmsBlock()

    async def _get_autonomy_block(self) -> AutonomyBlock:
        """从 runtime_config 获取自主模式级别。"""
        try:
            from app.core.runtime_config import get_autonomy_level
            level = await get_autonomy_level()
            meta = AUTONOMY_META.get(level, {"label": level, "color": "#8b5cf6"})

            # 判断是否运行中：通过是否有活跃 AUTO_EXECUTING 计划
            return AutonomyBlock(
                level=level,
                level_label=meta["label"],
                is_running=True,  # 简化：只要服务运行则为 True
                color=meta["color"],
            )
        except Exception as e:
            logger.warning(f"[SA] Failed to get autonomy block: {e}")
            return AutonomyBlock()

    def has_changed(
        self,
        prev: Optional[SituationalAwarenessSnapshot],
        curr: SituationalAwarenessSnapshot,
    ) -> bool:
        """检测关键字段是否变化（用于 WebSocket 推送决策）。"""
        if prev is None:
            return True

        if prev.regime.regime_type != curr.regime.regime_type:
            return True
        if abs((prev.var.usage_ratio or 0) - (curr.var.usage_ratio or 0)) > 0.05:
            return True
        if prev.active_fences.count != curr.active_fences.count:
            return True
        if prev.active_executions.count != curr.active_executions.count:
            return True
        if prev.pending_confirms.count != curr.pending_confirms.count:
            return True
        if prev.autonomy.level != curr.autonomy.level:
            return True

        return False


situational_awareness_service = SituationalAwarenessService()
