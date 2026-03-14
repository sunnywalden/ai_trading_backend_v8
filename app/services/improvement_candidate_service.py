"""V11.0.1 M3 — ImprovementCandidateService

根据 MetaStateSnapshot 自动生成可落地的改进候选，
用于 Improvement Lab / Learning Coach / CIO 面板展示。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.improvement_candidate import ImprovementCandidate


class ImprovementCandidateService:
    @staticmethod
    def _serialize(candidate: ImprovementCandidate) -> dict[str, Any]:
        return {
            "id": int(candidate.id),
            "account_id": str(candidate.account_id),
            "candidate_type": str(candidate.candidate_type),
            "target_module": str(candidate.target_module),
            "target_param": str(candidate.target_param),
            "current_value": candidate.current_value,
            "suggested_value": candidate.suggested_value,
            "confidence": float(candidate.confidence or 0.0),
            "trigger_source": candidate.trigger_source,
            "status": str(candidate.status),
            "evidence_summary": candidate.evidence_summary,
            "expected_impact": candidate.expected_impact,
            "validation_plan": candidate.validation_plan,
            "reviewed_at": (
                candidate.reviewed_at.isoformat() if candidate.reviewed_at else None
            ),
            "created_at": (
                candidate.created_at.isoformat() if candidate.created_at else None
            ),
        }

    async def _maybe_create_idle_capital_candidate(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        idle_ratio: float,
    ) -> ImprovementCandidate | None:
        if idle_ratio <= float(settings.IDLE_CAPITAL_ALERT_THRESHOLD or 0.25):
            return None
        current_factor = float(settings.IDLE_CAPITAL_GEA_HEADROOM_FACTOR or 0.0)
        alert_threshold = float(settings.IDLE_CAPITAL_ALERT_THRESHOLD or 0.25)
        return await self._create_candidate_if_missing(
            db,
            account_id=account_id,
            candidate_type="sizing_adjustment",
            target_module="gross_exposure_allocator",
            target_param="idle_capital_headroom_factor",
            current_value=current_factor,
            suggested_value=min(current_factor + 0.1, 1.0),
            confidence=0.82,
            trigger_source="idle_capital_persist",
            evidence_summary=(
                f"idle_cash_ratio={idle_ratio:.2%} 超过阈值 " f"{alert_threshold:.2%}"
            ),
            expected_impact="提升闲置资本释放效率，减少 no-headroom 导致的静默跳过。",
            validation_plan="观察 7 天内 idle_capital_adjusted 信号执行率与成交后收益变化。",
        )

    async def _maybe_create_friction_candidate(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        active_friction: int,
        soft_relief_eligible: int,
    ) -> ImprovementCandidate | None:
        if active_friction <= 0 or soft_relief_eligible <= 0:
            return None
        return await self._create_candidate_if_missing(
            db,
            account_id=account_id,
            candidate_type="threshold_tuning",
            target_module="signal_quality_funnel",
            target_param="soft_threshold_delta",
            current_value=0.0,
            suggested_value=1.0,
            confidence=0.76,
            trigger_source="friction_accumulation",
            evidence_summary=(
                f"active_friction_tickers={active_friction}, "
                f"soft_relief_eligible={soft_relief_eligible}"
            ),
            expected_impact="减少高质量近命中信号的重复拒绝，改善成功率优先前提下的资本速度。",
            validation_plan="对比 soft-threshold 触发前后通过率、命中率与回撤变化。",
        )

    async def _maybe_create_false_hold_candidate(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        false_hold_count: int,
    ) -> ImprovementCandidate | None:
        if false_hold_count <= 0:
            return None
        current_rounds = int(getattr(settings, "FALSE_HOLD_DETECTION_ROUNDS", 3))
        return await self._create_candidate_if_missing(
            db,
            account_id=account_id,
            candidate_type="risk_rule_adjustment",
            target_module="position_rebalance_monitor",
            target_param="false_hold_detection_rounds",
            current_value=float(current_rounds),
            suggested_value=float(max(2, current_rounds - 1)),
            confidence=0.84,
            trigger_source="false_hold_repeat",
            evidence_summary=(
                f"false_hold_count={false_hold_count}，"
                "存在 REDUCE/EXIT 被连续压制迹象"
            ),
            expected_impact="更早暴露被压制的风险释放场景，减少假持有造成的浮亏拖延。",
            validation_plan="跟踪 False-Hold 告警后 5 个交易日内的减仓执行率与浮亏收敛情况。",
        )

    async def list_candidates(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ImprovementCandidate)
            .where(ImprovementCandidate.account_id == account_id)
            .order_by(desc(ImprovementCandidate.created_at))
            .limit(max(1, min(limit, 100)))
        )
        if status:
            stmt = stmt.where(ImprovementCandidate.status == status)
        rows = (await db.execute(stmt)).scalars().all()
        return [self._serialize(row) for row in rows]

    async def generate_from_meta_state(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        snapshot: Any,
    ) -> list[dict[str, Any]]:
        if not bool(settings.IMPROVEMENT_ENGINE_V1101_ENABLED):
            return []

        snap = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
        if not isinstance(snap, dict):
            return []

        created: list[ImprovementCandidate] = []
        capital_state = snap.get("capital_state") or {}
        model_state = snap.get("model_state") or {}

        idle_ratio = float(capital_state.get("idle_cash_ratio") or 0.0)
        active_friction = int(model_state.get("active_friction_tickers") or 0)
        soft_relief_eligible = int(model_state.get("soft_relief_eligible_count") or 0)
        false_hold_count = int(model_state.get("false_hold_count") or 0)

        builders = [
            self._maybe_create_idle_capital_candidate(
                db,
                account_id=account_id,
                idle_ratio=idle_ratio,
            ),
            self._maybe_create_friction_candidate(
                db,
                account_id=account_id,
                active_friction=active_friction,
                soft_relief_eligible=soft_relief_eligible,
            ),
            self._maybe_create_false_hold_candidate(
                db,
                account_id=account_id,
                false_hold_count=false_hold_count,
            ),
        ]
        for candidate in builders:
            resolved = await candidate
            if resolved is not None:
                created.append(resolved)

        if created:
            await db.commit()
            for row in created:
                await db.refresh(row)

        return [self._serialize(row) for row in created]

    async def _create_candidate_if_missing(
        self,
        db: AsyncSession,
        *,
        account_id: str,
        candidate_type: str,
        target_module: str,
        target_param: str,
        current_value: float | None,
        suggested_value: float | None,
        confidence: float,
        trigger_source: str,
        evidence_summary: str,
        expected_impact: str,
        validation_plan: str,
    ) -> ImprovementCandidate | None:
        existing_stmt = select(ImprovementCandidate).where(
            and_(
                ImprovementCandidate.account_id == account_id,
                ImprovementCandidate.target_module == target_module,
                ImprovementCandidate.target_param == target_param,
                ImprovementCandidate.status == "pending",
            )
        )
        existing = (await db.execute(existing_stmt)).scalars().first()
        if existing is not None:
            return None

        candidate = ImprovementCandidate(
            account_id=account_id,
            candidate_type=candidate_type,
            target_module=target_module,
            target_param=target_param,
            current_value=current_value,
            suggested_value=suggested_value,
            confidence=confidence,
            trigger_source=trigger_source,
            status="pending",
            evidence_summary=evidence_summary,
            expected_impact=expected_impact,
            validation_plan=validation_plan,
        )
        db.add(candidate)
        await db.flush()
        return candidate


improvement_candidate_service = ImprovementCandidateService()
