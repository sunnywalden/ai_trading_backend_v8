"""V10.4.2: SignalAuditLogService — 信号漏斗审计日志服务

负责 signal_quality_audit_logs 表的读写操作。
前端 Signal Watchtower 页面通过此服务获取拒绝分布和漏斗统计。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal_quality_audit_log import (FunnelResult,
                                                 SignalQualityAuditLog)
from app.services.signal_conviction_scorer import ConvictionComponents

logger = logging.getLogger(__name__)


class SignalAuditLogService:
    """信号漏斗审计日志的 CRUD 及统计服务。"""

    _FALLBACK_PASS_STATUSES = {
        "VALIDATED",
        "QUEUED",
        "EXECUTING",
        "EXECUTED",
        "FAILED",
        "SKIPPED",
        "CANCELLED",
        "EXPIRED",
    }

    @staticmethod
    def _normalize_signal_lists(payload: dict[str, Any]) -> dict[str, list[str]]:
        def _as_list(key: str) -> list[str]:
            value = payload.get(key)
            if not isinstance(value, list):
                return []
            return [str(item) for item in value if item is not None]

        return {
            "aligned_dims": _as_list("aligned_dims"),
            "opposing_dims": _as_list("opposing_dims"),
            "neutral_dims": _as_list("neutral_dims"),
        }

    @staticmethod
    def _normalize_generated_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        return None

    @staticmethod
    def _derive_watchtower_state(signal: Any) -> dict[str, Any]:
        extra = signal.extra_metadata if isinstance(signal.extra_metadata, dict) else {}
        risk_details = (
            signal.risk_check_details
            if isinstance(getattr(signal, "risk_check_details", None), dict)
            else {}
        )
        status = str(getattr(getattr(signal, "status", None), "value", getattr(signal, "status", "")))
        watchtower_result = extra.get("watchtower_result")
        if watchtower_result in {"PASSED", "REJECTED"}:
            return {
                "result": watchtower_result,
                "stage": extra.get("watchtower_stage"),
                "reason_code": (
                    extra.get("watchtower_reason_code")
                    or extra.get("funnel_rejection_reason")
                ),
                "reason_detail": (
                    extra.get("watchtower_reason_detail")
                    or extra.get("funnel_rejection_detail")
                ),
                "rejected_at_layer": (
                    extra.get("watchtower_rejected_at_layer")
                    if extra.get("watchtower_rejected_at_layer") is not None
                    else extra.get("funnel_rejected_at_layer")
                ),
                "reason_category": extra.get("watchtower_reason_category"),
                "regime": extra.get("watchtower_regime") or extra.get("regime"),
            }

        if status == "VALIDATED" and getattr(signal, "risk_check_passed", None) == "YES":
            return {
                "result": "PASSED",
                "stage": "SIGNAL_VALIDATION",
                "reason_code": None,
                "reason_detail": None,
                "rejected_at_layer": None,
                "reason_category": "VALIDATION",
                "regime": extra.get("watchtower_regime") or extra.get("regime"),
            }

        if status == "REJECTED" and getattr(signal, "risk_check_passed", None) == "NO":
            detail = str(risk_details.get("reason") or "Signal validation blocked")
            return {
                "result": "REJECTED",
                "stage": "SIGNAL_VALIDATION",
                "reason_code": (
                    "TRADING_MODE_OFF"
                    if detail == "Trading mode is OFF"
                    else "SIGNAL_VALIDATION_BLOCKED"
                ),
                "reason_detail": detail,
                "rejected_at_layer": None,
                "reason_category": "VALIDATION",
                "regime": extra.get("watchtower_regime") or extra.get("regime"),
            }

        if status == "REJECTED" and getattr(signal, "risk_check_passed", None) == "YES":
            return {
                "result": "REJECTED",
                "stage": "QUALITY_FUNNEL",
                "reason_code": (
                    extra.get("watchtower_reason_code")
                    or extra.get("funnel_rejection_reason")
                    or "QUALITY_FUNNEL_PRE_INTENT_REJECTED"
                ),
                "reason_detail": (
                    extra.get("watchtower_reason_detail")
                    or extra.get("funnel_rejection_detail")
                    or (
                        "Legacy signal was rejected after validation "
                        "before execution intent was created"
                    )
                ),
                "rejected_at_layer": (
                    extra.get("watchtower_rejected_at_layer")
                    if extra.get("watchtower_rejected_at_layer") is not None
                    else extra.get("funnel_rejected_at_layer")
                ),
                "reason_category": (
                    extra.get("watchtower_reason_category")
                    or "QUALITY_FUNNEL"
                ),
                "regime": extra.get("watchtower_regime") or extra.get("regime"),
            }

        return {
            "result": "REJECTED" if status == "REJECTED" else "PASSED",
            "stage": None,
            "reason_code": None,
            "reason_detail": None,
            "rejected_at_layer": None,
            "reason_category": None,
            "regime": extra.get("watchtower_regime") or extra.get("regime"),
        }

    async def _count_fallback_candidates(
        self,
        db: AsyncSession,
        *,
        cutoff: datetime,
    ) -> int:
        from app.models.trading_signal import (SignalSource, SignalType,
                                               TradingSignal)

        stmt = select(func.count()).select_from(TradingSignal).where(
            and_(
                TradingSignal.created_at >= cutoff,
                TradingSignal.signal_source == SignalSource.STRATEGY,
                TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
                TradingSignal.status != "GENERATED",
            )
        )
        return (await db.execute(stmt)).scalar_one_or_none() or 0

    async def _should_use_signal_fallback(
        self,
        db: AsyncSession,
        *,
        cutoff: datetime,
    ) -> bool:
        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(SignalQualityAuditLog)
                .where(SignalQualityAuditLog.created_at >= cutoff)
            )
        ).scalar_one_or_none() or 0
        signal_count = await self._count_fallback_candidates(db, cutoff=cutoff)
        if signal_count == 0:
            return False
        if audit_count == 0:
            return True
        return audit_count * 3 < signal_count

    async def _current_regime_name(self, db: AsyncSession) -> str:
        try:
            from app.services.regime_classifier import RegimeClassifier

            current = await RegimeClassifier.get_current_regime(db)
            if current and getattr(current, "regime", None):
                return str(current.regime)
        except Exception:
            pass
        return "SIDEWAYS"

    def _fallback_quality_snapshot(
        self,
        signal: Any,
        *,
        regime: str,
    ) -> tuple[float | None, float | None, str | None, bool]:
        try:
            from app.services.signal_quality_funnel import (
                SignalFunnelInput, signal_quality_funnel)

            extra = signal.extra_metadata if isinstance(signal.extra_metadata, dict) else {}
            factor = signal.factor_scores if isinstance(signal.factor_scores, dict) else {}
            lists = self._normalize_signal_lists({
                "aligned_dims": extra.get("aligned_dims") or factor.get("aligned_dims"),
                "opposing_dims": extra.get("opposing_dims") or factor.get("opposing_dims"),
                "neutral_dims": extra.get("neutral_dims") or factor.get("neutral_dims"),
            })

            confidence = float(getattr(signal, "confidence", 0.0) or 0.0)
            composite_ratio = confidence / 100.0 if confidence > 1.0 else confidence
            funnel_input = SignalFunnelInput(
                signal_id=getattr(signal, "id", None),
                symbol=str(getattr(signal, "symbol", "") or ""),
                direction=str(getattr(signal, "direction", "LONG") or "LONG").upper(),
                regime=regime,
                signal_type=str(getattr(signal, "signal_type", "ENTRY") or "ENTRY").upper(),
                signal_strength=float(getattr(signal, "signal_strength", 0.0) or 0.0),
                composite_score=composite_ratio,
                aligned_count=int(
                    (extra.get("aligned_count") or factor.get("aligned_count") or 0)
                ),
                aligned_dims=lists["aligned_dims"],
                opposing_dims=lists["opposing_dims"],
                neutral_dims=lists["neutral_dims"],
                historical_ic=extra.get("historical_ic") or factor.get("historical_ic"),
                timing_quality=extra.get("timing_quality") or factor.get("timing_quality"),
                adv_usd=extra.get("adv_usd") or factor.get("adv_usd"),
                market_cap=extra.get("market_cap") or factor.get("market_cap"),
            )
            profile = signal_quality_funnel.preview_quality(funnel_input)
            composite_score = round(composite_ratio * 100.0, 2)
            return (
                round(profile.score, 2),
                composite_score,
                profile.tier,
                bool(profile.conviction and profile.conviction.anti_resonance_killed),
            )
        except Exception:
            confidence = float(getattr(signal, "confidence", 0.0) or 0.0)
            composite_score = confidence / 100.0 if confidence > 1.0 else confidence
            return (None, round(composite_score * 100.0, 2), None, False)

    def _fallback_signal_to_dict(
        self,
        signal: Any,
        *,
        regime: str,
    ) -> dict[str, Any]:
        extra = signal.extra_metadata if isinstance(signal.extra_metadata, dict) else {}
        factor = signal.factor_scores if isinstance(signal.factor_scores, dict) else {}
        watchtower = self._derive_watchtower_state(signal)
        lists = self._normalize_signal_lists({
            "aligned_dims": extra.get("aligned_dims") or factor.get("aligned_dims"),
            "opposing_dims": extra.get("opposing_dims") or factor.get("opposing_dims"),
            "neutral_dims": extra.get("neutral_dims") or factor.get("neutral_dims"),
        })
        conviction_score, composite_score, _, anti_kill = (
            self._fallback_quality_snapshot(signal, regime=regime)
        )
        return {
            "id": getattr(signal, "id", None),
            "signal_id": getattr(signal, "id", None),
            "symbol": getattr(signal, "symbol", None),
            "funnel_result": watchtower["result"],
            "decision_stage": watchtower["stage"],
            "reason_category": watchtower["reason_category"],
            "result_source": "TRADING_SIGNAL_METADATA",
            "rejected_at_layer": watchtower["rejected_at_layer"],
            "rejection_reason": watchtower["reason_code"],
            "rejection_detail": (
                watchtower["reason_detail"] or getattr(signal, "notes", None)
            ),
            "conviction_score": conviction_score,
            "composite_score": extra.get("signal_quality_score") or composite_score,
            "resonance_bonus": None,
            "regime_alignment": None,
            "calibrated_lower_bound": None,
            "aligned_count": int(extra.get("aligned_count") or factor.get("aligned_count") or 0),
            "aligned_dims": lists["aligned_dims"],
            "opposing_dims": lists["opposing_dims"],
            "neutral_dims": lists["neutral_dims"],
            "anti_resonance_triggered": anti_kill,
            "signal_direction": getattr(signal, "direction", None),
            "regime": watchtower["regime"] or regime,
            "concurrent_positions": extra.get("concurrent_positions"),
            "daily_signals_used": extra.get("daily_signals_used"),
            "generated_at": (
                signal.generated_at.isoformat() if getattr(signal, "generated_at", None) else None
            ),
            "evaluated_at": (
                signal.updated_at.isoformat() if getattr(signal, "updated_at", None) else None
            ),
            "created_at": (
                signal.created_at.isoformat() if getattr(signal, "created_at", None) else None
            ),
        }

    async def _get_recent_signal_fallback(
        self,
        db: AsyncSession,
        *,
        limit: int,
        offset: int,
        funnel_result: Optional[str],
        symbol: Optional[str],
        since_days: int,
    ) -> list[dict[str, Any]]:
        from app.models.trading_signal import (SignalSource, SignalType,
                                               TradingSignal)

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions = [
            TradingSignal.created_at >= cutoff,
            TradingSignal.signal_source == SignalSource.STRATEGY,
            TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
            TradingSignal.status != "GENERATED",
        ]
        if funnel_result == FunnelResult.PASSED:
            conditions.append(TradingSignal.status.in_(list(self._FALLBACK_PASS_STATUSES)))
        elif funnel_result == FunnelResult.REJECTED:
            conditions.append(TradingSignal.status == "REJECTED")
        if symbol:
            conditions.append(TradingSignal.symbol == symbol)

        stmt = (
            select(TradingSignal)
            .where(and_(*conditions))
            .order_by(desc(TradingSignal.created_at), desc(TradingSignal.id))
            .offset(offset)
            .limit(limit)
        )
        regime = await self._current_regime_name(db)
        rows = (await db.execute(stmt)).scalars().all()
        return [self._fallback_signal_to_dict(row, regime=regime) for row in rows]

    async def _get_funnel_stats_signal_fallback(
        self,
        db: AsyncSession,
        *,
        since_days: int,
    ) -> dict[str, Any]:
        from app.models.trading_signal import (SignalSource, SignalType,
                                               TradingSignal)

        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions = [
            TradingSignal.created_at >= cutoff,
            TradingSignal.signal_source == SignalSource.STRATEGY,
            TradingSignal.signal_type.in_([SignalType.ENTRY, SignalType.ADD]),
            TradingSignal.status != "GENERATED",
        ]

        stmt = (
            select(TradingSignal)
            .where(and_(*conditions))
            .order_by(TradingSignal.created_at.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            return {
                "since_days": since_days,
                "total_evaluated": 0,
                "total_passed": 0,
                "total_rejected": 0,
                "elite_rate_pct": 0.0,
                "layer_stats": {
                    "layer_0_rejected": 0,
                    "layer_1_rejected": 0,
                    "layer_2_rejected": 0,
                    "layer_3_rejected": 0,
                    "layer_4_rejected": 0,
                },
                "rejection_breakdown": {},
                "daily_trend": [],
                "fallback_mode": True,
            }

        total = len(rows)
        layer_stats = {
            "layer_0_rejected": 0,
            "layer_1_rejected": 0,
            "layer_2_rejected": 0,
            "layer_3_rejected": 0,
            "layer_4_rejected": 0,
        }
        rejection_breakdown: dict[str, int] = {}
        passed = sum(
            1
            for row in rows
            if str(self._derive_watchtower_state(row)["result"])
            in self._FALLBACK_PASS_STATUSES.union({"PASSED"})
        )
        daily_map: dict[str, dict[str, int]] = {}
        for row in rows:
            if not getattr(row, "created_at", None):
                continue
            watchtower = self._derive_watchtower_state(row)
            day_key = str(row.created_at.date())
            bucket = daily_map.setdefault(day_key, {"passed": 0, "total": 0})
            bucket["total"] += 1
            status = str(watchtower["result"])
            if status in self._FALLBACK_PASS_STATUSES or status == "PASSED":
                bucket["passed"] += 1
            else:
                reason = watchtower["reason_code"]
                if reason:
                    rejection_breakdown[reason] = rejection_breakdown.get(reason, 0) + 1
                layer = watchtower["rejected_at_layer"]
                if isinstance(layer, int) and 0 <= layer <= 4:
                    layer_stats[f"layer_{layer}_rejected"] += 1

        daily_trend = [
            {
                "date": day,
                "passed": values["passed"],
                "total": values["total"],
                "elite_rate": round(values["passed"] / max(1, values["total"]) * 100, 1),
            }
            for day, values in sorted(daily_map.items())
        ]

        return {
            "since_days": since_days,
            "total_evaluated": total,
            "total_passed": passed,
            "total_rejected": total - passed,
            "elite_rate_pct": round(passed / max(1, total) * 100, 1),
            "layer_stats": layer_stats,
            "rejection_breakdown": rejection_breakdown,
            "daily_trend": daily_trend,
            "fallback_mode": True,
        }

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
            generated_at         = self._normalize_generated_at(generated_at),
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
        if await self._should_use_signal_fallback(db, cutoff=cutoff):
            return await self._get_recent_signal_fallback(
                db,
                limit=limit,
                offset=offset,
                funnel_result=funnel_result,
                symbol=symbol,
                since_days=since_days,
            )

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
        if await self._should_use_signal_fallback(db, cutoff=cutoff):
            return await self._get_funnel_stats_signal_fallback(
                db,
                since_days=since_days,
            )

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
            "decision_stage":          "QUALITY_FUNNEL",
            "reason_category":         "QUALITY_FUNNEL",
            "result_source":           "SIGNAL_QUALITY_AUDIT_LOG",
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
