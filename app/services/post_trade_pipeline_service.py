"""post_trade_pipeline_service.py — V10.3 交易后生命周期推进服务

职责：驱动 Pipeline S12 → S13 → S14 → S15 → S16 的自动流转。

触发机制：
  - 定时 Job 每 5 分钟调用一次（quant_loop_jobs.run_post_trade_pipeline_job）
  - 亦可在 broker 对账后手动触发

阶段推进逻辑（以 stage_entered_at + P50 benchmark 作为最小等待时间）：
  S12 (订单结算,   P50=60s)  → S13
  S13 (归因分析,  P50=120s)  → S14
  S14 (洞察更新,  P50=300s)  → S15
  S15 (A/B实验,    P50=60s)  → S16  plan_status → COMPLETED_SETTLE
  S16 已完成：不再推进

对于 pipeline_stage IS NULL 且 plan_status='EXECUTED' 的孤立计划，
直接修正为 S12 入口并触发推进。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fsm_transition_log import FsmTransitionLog
from app.models.trading_plan import TradingPlan

logger = logging.getLogger(__name__)
_SH_TZ = ZoneInfo("Asia/Shanghai")

# 各阶段最小停留秒数（取 P50 × 1，即达到 P50 时立即推进）
_MIN_SECS: dict[int, int] = {
    12: 60,
    13: 120,
    14: 300,
    15: 60,
}

# S12-S15 推进到下一阶段的映射
_NEXT_STAGE: dict[int, int] = {12: 13, 13: 14, 14: 15, 15: 16}

# pipeline_stage → position_fsm_state 映射（post-trade 阶段全部视为 CLOSED）
_STAGE_TO_POS_FSM: dict[int, str] = {
    7: "ENTERING", 8: "ENTERING",
    9: "HELD", 10: "SCALING_IN", 11: "EXITING_FULL",
    12: "CLOSED", 13: "CLOSED", 14: "CLOSED", 15: "CLOSED", 16: "CLOSED",
}


class PostTradePipelineService:
    """驱动 Post-Trade Pipeline S12→S16 自动流转。"""

    @staticmethod
    def _normalize_entered_at(entered: datetime, now: datetime) -> datetime:
        """标准化 stage_entered_at 到 UTC。

        历史数据里存在无时区 datetime。默认按 UTC 解释；
        若结果落在“未来时间”，再尝试按 Asia/Shanghai 解释做一次回退，
        以兼容旧数据/旧脚本写入导致的时区漂移，避免计划长期无法推进。
        """
        if entered.tzinfo is not None:
            return entered.astimezone(timezone.utc)

        as_utc = entered.replace(tzinfo=timezone.utc)
        if as_utc <= now + timedelta(seconds=30):
            return as_utc

        # 未来时间兜底：尝试按上海时区解释旧的 naive 时间
        as_sh = entered.replace(tzinfo=_SH_TZ).astimezone(timezone.utc)
        if as_sh <= now + timedelta(seconds=30):
            return as_sh

        # 双重解释都在未来，则退回默认解释
        return as_utc

    async def advance_post_trade_plans(
        self,
        db: AsyncSession,
        account_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """扫描并推进所有处于 S12-S15 的计划。

        Args:
            db: 数据库 Session（调用方负责 commit）。
            account_id: 仅处理该账户；None 表示处理所有账户。
            dry_run: 不写入数据库，仅返回统计。

        Returns:
            dict with keys: scanned, advanced, by_stage
        """
        now = datetime.now(timezone.utc)

        # ── 1. 先修正：pipeline_stage IS NULL 且 EXECUTED 的孤立计划 → S12 ──
        orphan_cond = and_(
            TradingPlan.pipeline_stage.is_(None),
            TradingPlan.plan_status == "EXECUTED",
        )
        if account_id:
            orphan_cond = and_(orphan_cond, TradingPlan.account_id == account_id)
        orphan_plans = (await db.execute(select(TradingPlan).where(orphan_cond))).scalars().all()

        repaired = 0
        for plan in orphan_plans:
            if dry_run:
                repaired += 1
                continue
            plan.pipeline_stage = 12
            plan.stage_entered_at = now - timedelta(seconds=120)  # 视为已就绪
            plan.position_fsm_state = "CLOSED"  # 进入结算即视为仓位已关闭
            db.add(FsmTransitionLog(
                plan_id=plan.id,
                fsm_type="PLAN",
                from_state="STAGE_NULL",
                to_state="STAGE_12",
                trigger_reason="post_trade_pipeline: 孤立EXECUTED计划修正至S12",
            ))
            repaired += 1

        if repaired and not dry_run:
            await db.flush()
            logger.info("[PostTradePipeline] repaired %d orphan EXECUTED plans → S12", repaired)

        # ── 2. 扫描 S12-S15 中等待推进的计划 ──────────────────────────────────
        stage_cond = TradingPlan.pipeline_stage.in_(list(_NEXT_STAGE.keys()))
        status_cond = TradingPlan.plan_status.notin_(["CANCELLED", "EXPIRED", "FAILED", "REVOKED"])
        base_cond = and_(stage_cond, status_cond)
        if account_id:
            base_cond = and_(base_cond, TradingPlan.account_id == account_id)

        plans = (await db.execute(select(TradingPlan).where(base_cond))).scalars().all()

        advanced = 0
        by_stage: dict[int, int] = {}

        for plan in plans:
            stage = plan.pipeline_stage
            if stage not in _NEXT_STAGE:
                continue

            min_secs = _MIN_SECS.get(stage, 60)
            entered = plan.stage_entered_at
            if entered is not None:
                entered = self._normalize_entered_at(entered, now)
                elapsed = (now - entered).total_seconds()
                if elapsed < min_secs:
                    continue  # 还未到 P50，暂不推进

            # 推进到下一阶段
            next_stage = _NEXT_STAGE[stage]
            old_stage = stage

            if not dry_run:
                plan.pipeline_stage = next_stage
                plan.stage_entered_at = now
                plan.position_fsm_state = _STAGE_TO_POS_FSM.get(next_stage, "CLOSED")

                # S16：标记为 pipeline 完成（plan_status 保持语义不变，仅打 tag）
                if next_stage == 16:
                    tags = dict(plan.plan_tags or {})
                    tags["pipeline_completed_at"] = now.isoformat()
                    plan.plan_tags = tags

                db.add(FsmTransitionLog(
                    plan_id=plan.id,
                    fsm_type="PLAN",
                    from_state=f"STAGE_{old_stage}",
                    to_state=f"STAGE_{next_stage}",
                    trigger_reason=f"post_trade_pipeline: S{old_stage}→S{next_stage} auto-advance",
                ))

            advanced += 1
            by_stage[old_stage] = by_stage.get(old_stage, 0) + 1

        if advanced and not dry_run:
            await db.flush()
            logger.info(
                "[PostTradePipeline] advanced %d plans: %s",
                advanced,
                {f"S{k}→S{v}": cnt for (k, cnt), v in zip(by_stage.items(), [_NEXT_STAGE[s] for s in by_stage])},
            )

        return {
            "scanned": len(plans),
            "repaired_orphans": repaired,
            "advanced": advanced,
            "by_stage": by_stage,
            "dry_run": dry_run,
        }


post_trade_pipeline_service = PostTradePipelineService()
