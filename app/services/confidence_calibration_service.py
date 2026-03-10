"""confidence_calibration_service.py — V10.3.3 置信度校准服务

每日 08:15 运行：
1. 拉取过去 90 天所有信号的置信度 + 实际胜率
2. 按 bucket (0.0-0.1, 0.1-0.2 … 0.9-1.0) 统计
3. 计算 Brier Score 和 ECE
4. ECE > 0.12 → 置信度降评（向 0.5 收缩）
5. 写入 confidence_calibration_snapshot
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.confidence_calibration_snapshot import ConfidenceCalibrationSnapshot

logger = logging.getLogger(__name__)

ECE_WARN_THRESHOLD: float = 0.12   # ECE 告警阈值
LOOKBACK_DAYS: int = 90
BUCKET_SIZE: float = 0.1


def _brier_score(predicted: list[float], outcomes: list[float]) -> float:
    """Brier Score = mean((p - o)^2)，越低越好。"""
    if not predicted:
        return 0.0
    return float(np.mean([(p - o) ** 2 for p, o in zip(predicted, outcomes)]))


def _ece(calibration_buckets: list[dict]) -> float:
    """
    ECE = sum_b (|bucket| / N) * |predicted_rate_b - actual_rate_b|
    calibration_buckets: [{count, predicted_rate, actual_rate}]
    """
    total = sum(b["count"] for b in calibration_buckets)
    if total == 0:
        return 0.0
    return float(sum(
        (b["count"] / total) * abs(b["predicted_rate"] - b["actual_rate"])
        for b in calibration_buckets
        if b["count"] > 0
    ))


def _calibration_adjustment_factor(ece: float) -> float:
    """线性从 ECE 映射到收缩因子（ECE→0.12 时收缩 0，ECE→0.3 时收缩 0.3）。"""
    if ece <= ECE_WARN_THRESHOLD:
        return 0.0
    return min(0.5, (ece - ECE_WARN_THRESHOLD) / 0.3)


def apply_calibration(confidence: float, adjustment_factor: float) -> float:
    """向 0.5 收缩置信度：c_adj = c + α * (0.5 - c)"""
    return confidence + adjustment_factor * (0.5 - confidence)


def _parse_bucket_range(bucket: Any) -> tuple[float | None, float | None]:
    """从 bucket 字符串（如 0.0-0.1）解析数值边界。"""
    if not isinstance(bucket, str) or "-" not in bucket:
        return None, None
    left, right = bucket.split("-", 1)
    try:
        return float(left), float(right)
    except (TypeError, ValueError):
        return None, None


def _normalize_calibration_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """补齐 bucket_start / bucket_end，兼容历史 JSON 快照。"""
    normalized = dict(bucket)
    bucket_start = normalized.get("bucket_start")
    bucket_end = normalized.get("bucket_end")
    if isinstance(bucket_start, (int, float)) and isinstance(bucket_end, (int, float)):
        normalized["bucket_start"] = float(bucket_start)
        normalized["bucket_end"] = float(bucket_end)
        return normalized

    parsed_start, parsed_end = _parse_bucket_range(normalized.get("bucket"))
    normalized["bucket_start"] = parsed_start
    normalized["bucket_end"] = parsed_end
    return normalized


def _normalize_calibration_buckets(buckets: Any) -> list[dict[str, Any]] | None:
    """统一 bucket 结构，确保接口对新旧快照都返回完整边界字段。"""
    if not isinstance(buckets, list):
        return None
    return [
        _normalize_calibration_bucket(bucket)
        for bucket in buckets
        if isinstance(bucket, dict)
    ]


class ConfidenceCalibrationService:
    """置信度校准系统。"""

    async def run_daily_calibration(
        self, db: AsyncSession, account_id: str
    ) -> ConfidenceCalibrationSnapshot:
        """核心日度任务：计算 Brier/ECE 并写入快照。"""
        today = date.today()

        # 检查今日是否已运行（insufficient_data 快照会原地重算，不做删除重插）
        existing = await self._get_snapshot_by_date(db, account_id, today)
        if existing:
            if existing.brier_score is not None:
                logger.info("CalibrationService: snapshot already exists for %s, skipping", today)
                return existing
            logger.info("CalibrationService: stale insufficient_data snapshot found for %s, recomputing in-place", today)

        # 拉取数据（优先 trading_signal.actual_return，不足时回退 trade_journal）
        predicted, outcomes = await self._fetch_signal_outcomes(db, account_id, LOOKBACK_DAYS)

        if len(predicted) == 0:
            logger.warning("CalibrationService: insufficient data (%d samples), skipping", len(predicted))
            if existing:
                snap = existing
                snap.brier_score = None
                snap.ece = None
                snap.overconfidence_bias = None
                snap.calibration_buckets = None
                snap.lookback_days = LOOKBACK_DAYS
                snap.total_samples = len(predicted)
                snap.valid_bucket_count = None
                snap.needs_adjustment = False
                snap.adjustment_factor = None
                snap.adjustment_applied_at = None
            else:
                snap = ConfidenceCalibrationSnapshot(
                    account_id=account_id,
                    snapshot_date=today,
                    lookback_days=LOOKBACK_DAYS,
                    total_samples=len(predicted),
                    needs_adjustment=False,
                )
                db.add(snap)

            try:
                await db.flush()
            except IntegrityError as e:
                msg = str(e)
                if "idx_ccs_user_date" not in msg and "Duplicate entry" not in msg:
                    raise
                await db.rollback()
                latest = await self._get_snapshot_by_date(db, account_id, today)
                if latest:
                    logger.info("CalibrationService: duplicate snapshot race detected for %s, using existing", today)
                    return latest
                raise
            return snap

        # 计算 bucket 映射
        buckets = _build_calibration_buckets(predicted, outcomes)
        brier = _brier_score(predicted, outcomes)
        ece_val = _ece(buckets)
        overconf = float(np.mean([p - o for p, o in zip(predicted, outcomes)]))

        needs_adj = ece_val > ECE_WARN_THRESHOLD
        adj_factor = _calibration_adjustment_factor(ece_val) if needs_adj else None

        if existing:
            snap = existing
            snap.brier_score = round(brier, 6)
            snap.ece = round(ece_val, 6)
            snap.overconfidence_bias = round(overconf, 6)
            snap.calibration_buckets = buckets
            snap.lookback_days = LOOKBACK_DAYS
            snap.total_samples = len(predicted)
            snap.valid_bucket_count = sum(1 for b in buckets if b["count"] >= 10)
            snap.needs_adjustment = needs_adj
            snap.adjustment_factor = round(adj_factor, 4) if adj_factor else None
        else:
            snap = ConfidenceCalibrationSnapshot(
                account_id=account_id,
                snapshot_date=today,
                brier_score=round(brier, 6),
                ece=round(ece_val, 6),
                overconfidence_bias=round(overconf, 6),
                calibration_buckets=buckets,
                lookback_days=LOOKBACK_DAYS,
                total_samples=len(predicted),
                valid_bucket_count=sum(1 for b in buckets if b["count"] >= 10),
                needs_adjustment=needs_adj,
                adjustment_factor=round(adj_factor, 4) if adj_factor else None,
            )
            db.add(snap)

        try:
            await db.flush()
        except IntegrityError as e:
            msg = str(e)
            if "idx_ccs_user_date" not in msg and "Duplicate entry" not in msg:
                raise
            await db.rollback()
            latest = await self._get_snapshot_by_date(db, account_id, today)
            if latest:
                logger.info("CalibrationService: duplicate snapshot race detected for %s, using existing", today)
                return latest
            raise
        logger.info(
            "CalibrationService: date=%s brier=%.4f ece=%.4f needs_adj=%s",
            today, brier, ece_val, needs_adj,
        )
        return snap

    async def get_latest_calibration(
        self, db: AsyncSession, account_id: str
    ) -> dict[str, Any] | None:
        stmt = (
            select(ConfidenceCalibrationSnapshot)
            .where(ConfidenceCalibrationSnapshot.account_id == account_id)
            .order_by(desc(ConfidenceCalibrationSnapshot.snapshot_date))
            .limit(1)
        )
        snap = (await db.execute(stmt)).scalars().first()
        return _snap_to_dict(snap) if snap else None

    async def get_calibration_history(
        self, db: AsyncSession, account_id: str, days: int = 30
    ) -> list[dict[str, Any]]:
        cutoff = date.today() - timedelta(days=days)
        stmt = (
            select(ConfidenceCalibrationSnapshot)
            .where(
                ConfidenceCalibrationSnapshot.account_id == account_id,
                ConfidenceCalibrationSnapshot.snapshot_date >= cutoff,
            )
            .order_by(ConfidenceCalibrationSnapshot.snapshot_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_snap_to_dict(r) for r in rows]

    async def _fetch_signal_outcomes(
        self, db: AsyncSession, account_id: str, lookback_days: int
    ) -> tuple[list[float], list[float]]:
        """从 trading_signal 表拉取置信度 + 实际胜率对。

        当 actual_return 样本不足（< 20）时，自动从 trade_journal 补充历史数据。
        """
        from app.models.trading_signal import TradingSignal
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        predicted: list[float] = []
        outcomes: list[float] = []
        try:
            stmt = (
                select(TradingSignal.confidence, TradingSignal.actual_return)
                .where(
                    TradingSignal.user_id == account_id,
                    TradingSignal.created_at >= cutoff,
                    TradingSignal.actual_return.isnot(None),
                )
            )
            rows = (await db.execute(stmt)).all()
            predicted = [float(r.confidence or 0.5) for r in rows]
            outcomes = [1.0 if (r.actual_return or 0) > 0 else 0.0 for r in rows]
        except Exception as e:
            logger.warning("CalibrationService: fetch failed: %s", e)

        # Fallback：actual_return 样本不足时，从 trade_journal 历史记录补充
        if len(predicted) < 20:
            try:
                extra_pred, extra_out = await self._fetch_outcomes_from_journal(
                    db, account_id, cutoff
                )
                predicted.extend(extra_pred)
                outcomes.extend(extra_out)
            except Exception as e:
                logger.warning("CalibrationService: journal fallback failed: %s", e)

        return predicted, outcomes

    async def _fetch_outcomes_from_journal(
        self, db: AsyncSession, account_id: str, cutoff: datetime
    ) -> tuple[list[float], list[float]]:
        """从 trade_journal 已平仓记录构建校准样本（fallback）。

        以同期同 symbol 的 TradingSignal.confidence 作为预测置信度，
        以 realized_pnl > 0 作为实际胜率结果。
        """
        from app.models.trade_journal import TradeJournal
        from app.models.trading_signal import TradingSignal

        # 拉取已平仓 journal 记录：
        # 1) realized_pnl 已回写，或
        # 2) entry/exit 价格齐全（可推导收益）
        j_stmt = (
            select(
                TradeJournal.symbol,
                TradeJournal.entry_price,
                TradeJournal.exit_price,
                TradeJournal.quantity,
                TradeJournal.realized_pnl,
            )
            .where(
                TradeJournal.account_id == account_id,
                or_(
                    TradeJournal.realized_pnl.is_not(None),
                    and_(
                        TradeJournal.entry_price.is_not(None),
                        TradeJournal.exit_price.is_not(None),
                    ),
                ),
                TradeJournal.created_at >= cutoff,
            )
            .order_by(TradeJournal.created_at.desc())
        )
        journals = (await db.execute(j_stmt)).all()
        if not journals:
            # 90 天窗口为空时，回退到最近闭环交易样本，避免页面长期空白
            j_stmt_recent = (
                select(
                    TradeJournal.symbol,
                    TradeJournal.entry_price,
                    TradeJournal.exit_price,
                    TradeJournal.quantity,
                    TradeJournal.realized_pnl,
                )
                .where(
                    TradeJournal.account_id == account_id,
                    or_(
                        TradeJournal.realized_pnl.is_not(None),
                        and_(
                            TradeJournal.entry_price.is_not(None),
                            TradeJournal.exit_price.is_not(None),
                        ),
                    ),
                )
                .order_by(TradeJournal.created_at.desc())
                .limit(300)
            )
            journals = (await db.execute(j_stmt_recent)).all()
        if not journals:
            return [], []

        # 构建 symbol → 最新 confidence 映射（来自同期 TradingSignal）
        sig_stmt = (
            select(TradingSignal.symbol, TradingSignal.confidence)
            .where(
                TradingSignal.user_id == account_id,
                TradingSignal.created_at >= cutoff,
                TradingSignal.confidence.isnot(None),
            )
            .order_by(TradingSignal.created_at.desc())
        )
        sig_rows = (await db.execute(sig_stmt)).all()
        sym_conf: dict[str, float] = {}
        for s in sig_rows:
            k = (s.symbol or "").strip().upper()
            if k and k not in sym_conf:
                sym_conf[k] = float(s.confidence)

        predicted: list[float] = []
        outcomes: list[float] = []
        for j in journals:
            symbol = (j.symbol or "").strip().upper()
            ep = float(j.entry_price or 0)
            xp = float(j.exit_price or 0)
            qty = float(j.quantity or 0)
            realized_raw = j.realized_pnl
            realized = float(realized_raw or 0)
            if realized_raw is None and ep > 0 and xp > 0 and qty > 0:
                realized = (xp - ep) * qty
            if ep <= 0 or qty <= 0:
                continue
            confidence = sym_conf.get(symbol, 0.65)
            outcome = 1.0 if realized > 0 else 0.0
            predicted.append(confidence)
            outcomes.append(outcome)

        logger.info(
            "CalibrationService: journal fallback produced %d samples for user=%s",
            len(predicted), account_id,
        )
        return predicted, outcomes

    async def _get_snapshot_by_date(
        self, db: AsyncSession, account_id: str, snapshot_date: date
    ) -> ConfidenceCalibrationSnapshot | None:
        stmt = (
            select(ConfidenceCalibrationSnapshot)
            .where(
                ConfidenceCalibrationSnapshot.account_id == account_id,
                ConfidenceCalibrationSnapshot.snapshot_date == snapshot_date,
            )
        )
        return (await db.execute(stmt)).scalars().first()


def _build_calibration_buckets(
    predicted: list[float], outcomes: list[float]
) -> list[dict[str, Any]]:
    """按 0.1 步长分 bucket，统计预测率 vs 实际率。"""
    bucket_map: dict[str, list[tuple[float, float]]] = {}
    for p, o in zip(predicted, outcomes):
        b_lo = math.floor(p * 10) / 10
        b_hi = min(1.0, b_lo + BUCKET_SIZE)
        key = f"{b_lo:.1f}-{b_hi:.1f}"
        bucket_map.setdefault(key, []).append((p, o))

    result = []
    for b_lo_f in [i / 10 for i in range(10)]:
        b_hi_f = min(1.0, b_lo_f + BUCKET_SIZE)
        key = f"{b_lo_f:.1f}-{b_hi_f:.1f}"
        pairs = bucket_map.get(key, [])
        count = len(pairs)
        pred_rate = float(np.mean([p for p, _ in pairs])) if pairs else (b_lo_f + BUCKET_SIZE / 2)
        actual_rate = float(np.mean([o for _, o in pairs])) if pairs else 0.0
        result.append({
            "bucket": key,
            "bucket_start": round(b_lo_f, 4),
            "bucket_end": round(b_hi_f, 4),
            "count": count,
            "predicted_rate": round(pred_rate, 4),
            "actual_rate": round(actual_rate, 4),
            "gap": round(pred_rate - actual_rate, 4),
        })
    return result


def _snap_to_dict(snap: ConfidenceCalibrationSnapshot) -> dict[str, Any]:
    return {
        "id": snap.id,
        "snapshot_date": str(snap.snapshot_date),
        "brier_score": snap.brier_score,
        "ece": snap.ece,
        "overconfidence_bias": snap.overconfidence_bias,
        "calibration_buckets": _normalize_calibration_buckets(snap.calibration_buckets),
        "total_samples": snap.total_samples,
        "valid_bucket_count": snap.valid_bucket_count,
        "needs_adjustment": snap.needs_adjustment,
        "adjustment_factor": snap.adjustment_factor,
        "created_at": snap.created_at.isoformat() if snap.created_at else None,
    }


confidence_calibration_service = ConfidenceCalibrationService()
