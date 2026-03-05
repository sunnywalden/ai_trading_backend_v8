"""V10.4.2: SignalAuditLogService — 信号漏斗审计日志服务

负责 signal_quality_audit_logs 表的读写操作。
前端 Signal Watchtower 页面通过此服务获取拒绝分布和漏斗统计。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal_quality_audit_log import SignalQualityAuditLog, FunnelResult
from app.services.signal_conviction_scorer import ConvictionComponents

logger = logging.getLogger(__name__)


class SignalAuditLogService:
    """信号漏斗审计日志的 CRUD 及统计服务。"""

    async def create(
        self,
        db: AsyncSession,
        *,
        symbol: str,
        signal_id: Optional[int],
        funnel_result: str,
        rejected_at_layer:   Optional[int],
        rejection_reason:    Optional[str],
        rejection_detail:    Optional[str],
        conviction:          Optional[ConvictionComponents],
        composite_score:     Optional[float],
        aligned_count:       int,
        aligned_dims:        list[str],
        opposing_dims:       list[str],
        neutral_dims:        list[str],
        anti_resonance_triggered: bool,
        signal_direction:    Optional[str],
        regime:              Optional[str],
        concurrent_positions: int,
        daily_signals_used:   int,
        generated_at:        Optional[str],
    ) -> SignalQualityAuditLog:
        """创建一条新的审计日志记录。"""
        entry = SignalQualityAuditLog(
            signal_id            = signal_id,
            symbol               = symbol,
            funnel_result        = funnel_result,
            rejected_at_layer    = rejected_at_layer,
            rejection_reason     = rejection_reason,
            rejection_detail     = rejection_detail,
            conviction_score     = conviction.conviction_score if conviction else None,
            composite_score      = composite_score,
            resonance_bonus      = conviction.resonance_bonus if conviction else None,
            regime_alignment     = conviction.regime_alignment if conviction else None,
            calibrated_lower_bound = conviction.calibrated_lower_bound if conviction else None,
            aligned_count        = aligned_count,
            aligned_dims         = aligned_dims,
            opposing_dims        = opposing_dims,
            neutral_dims         = neutral_dims,
            anti_resonance_triggered = anti_resonance_triggered,
            signal_direction     = signal_direction,
            regime               = regime,
            concurrent_positions = concurrent_positions,
            daily_signals_used   = daily_signals_used,
            generated_at         = (
                datetime.fromisoformat(generated_at)
                if generated_at else None
            ),
            evaluated_at         = datetime.now(timezone.utc),
        )
        db.add(entry)
        await db.flush()
        return entry

    async def get_recent(
        self,
        db: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
        funnel_result: Optional[str] = None,
        symbol: Optional[str] = None,
        since_days: int = 30,
    ) -> list[dict]:
        """获取近期审计日志列表。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions = [SignalQualityAuditLog.created_at >= cutoff]
        if funnel_result:
            conditions.append(SignalQualityAuditLog.funnel_result == funnel_result)
        if symbol:
            conditions.append(SignalQualityAuditLog.symbol == symbol)

        stmt = (
            select(SignalQualityAuditLog)
            .where(and_(*conditions))
            .order_by(SignalQualityAuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(r) for r in rows]

    async def get_funnel_stats(
        self,
        db: AsyncSession,
        *,
        since_days: int = 7,
    ) -> dict:
        """计算漏斗各层通过/拒绝统计，用于 Signal Watchtower 漏斗流向图。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

        # 总数统计
        total_stmt = select(func.count()).select_from(SignalQualityAuditLog).where(
            SignalQualityAuditLog.created_at >= cutoff
        )
        total = (await db.execute(total_stmt)).scalar_one_or_none() or 0

        # 各层拒绝数
        layer_stats = {}
        for layer in range(5):
            stmt = select(func.count()).select_from(SignalQualityAuditLog).where(
                and_(
                    SignalQualityAuditLog.created_at >= cutoff,
                    SignalQualityAuditLog.rejected_at_layer == layer,
                )
            )
            cnt = (await db.execute(stmt)).scalar_one_or_none() or 0
            layer_stats[f"layer_{layer}_rejected"] = cnt

        # 通过数
        passed_stmt = select(func.count()).select_from(SignalQualityAuditLog).where(
            and_(
                SignalQualityAuditLog.created_at >= cutoff,
                SignalQualityAuditLog.funnel_result == FunnelResult.PASSED,
            )
        )
        passed = (await db.execute(passed_stmt)).scalar_one_or_none() or 0

        # 拒绝原因分布
        reason_stmt = (
            select(
                SignalQualityAuditLog.rejection_reason,
                func.count().label("cnt"),
            )
            .where(
                and_(
                    SignalQualityAuditLog.created_at >= cutoff,
                    SignalQualityAuditLog.rejection_reason.isnot(None),
                )
            )
            .group_by(SignalQualityAuditLog.rejection_reason)
            .order_by(func.count().desc())
        )
        reason_rows = (await db.execute(reason_stmt)).all()
        rejection_breakdown = {row[0]: row[1] for row in reason_rows}

        # 近 7 天精英率趋势
        daily_rate_stmt = (
            select(
                func.date(SignalQualityAuditLog.created_at).label("d"),
                func.sum(
                    func.if_(SignalQualityAuditLog.funnel_result == FunnelResult.PASSED, 1, 0)
                ).label("passed_cnt"),
                func.count().label("total_cnt"),
            )
            .where(SignalQualityAuditLog.created_at >= cutoff)
            .group_by(func.date(SignalQualityAuditLog.created_at))
            .order_by(func.date(SignalQualityAuditLog.created_at))
        )
        daily_rows = (await db.execute(daily_rate_stmt)).all()
        daily_trend = [
            {
                "date":        str(row[0]),
                "passed":      int(row[1] or 0),
                "total":       int(row[2] or 0),
                "elite_rate":  round(
                    (int(row[1] or 0) / max(1, int(row[2] or 0))) * 100, 1
                ),
            }
            for row in daily_rows
        ]

        return {
            "since_days":          since_days,
            "total_evaluated":     total,
            "total_passed":        passed,
            "total_rejected":      total - passed,
            "elite_rate_pct":      round(passed / max(1, total) * 100, 1),
            "layer_stats":         layer_stats,
            "rejection_breakdown": rejection_breakdown,
            "daily_trend":         daily_trend,
        }

    def _row_to_dict(self, r: SignalQualityAuditLog) -> dict:
        return {
            "id":                      r.id,
            "signal_id":               r.signal_id,
            "symbol":                  r.symbol,
            "funnel_result":           r.funnel_result,
            "rejected_at_layer":       r.rejected_at_layer,
            "rejection_reason":        r.rejection_reason,
            "rejection_detail":        r.rejection_detail,
            "conviction_score":        r.conviction_score,
            "composite_score":         r.composite_score,
            "resonance_bonus":         r.resonance_bonus,
            "regime_alignment":        r.regime_alignment,
            "calibrated_lower_bound":  r.calibrated_lower_bound,
            "aligned_count":           r.aligned_count,
            "aligned_dims":            r.aligned_dims,
            "opposing_dims":           r.opposing_dims,
            "neutral_dims":            r.neutral_dims,
            "anti_resonance_triggered": r.anti_resonance_triggered,
            "signal_direction":        r.signal_direction,
            "regime":                  r.regime,
            "concurrent_positions":    r.concurrent_positions,
            "daily_signals_used":      r.daily_signals_used,
            "generated_at":            r.generated_at.isoformat() if r.generated_at else None,
            "evaluated_at":            r.evaluated_at.isoformat() if r.evaluated_at else None,
            "created_at":              r.created_at.isoformat() if r.created_at else None,
        }


# ── 模块级单例 ────────────────────────────────────────────────────────────────
signal_audit_log_service = SignalAuditLogService()
