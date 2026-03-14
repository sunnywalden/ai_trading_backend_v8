"""
持仓再平衡监控器 — 将 AI 评分建议转化为可执行信号

职责：
  1. 读取当前账户持仓（来自 Broker）
  2. 查询每个持仓标的最新评分（PositionScore，24h 内有效）
  3. 将 REDUCE 建议 → SignalType.REDUCE（减仓 30-50%）
     将 SELL   建议 → SignalType.EXIT  （全部平仓）
  4. 写入 TradingSignal，状态 GENERATED，等待 AutonomousEngine 处理

V11.0.1 M2.3 增量：
  - False-Hold 检测：当同一标的 REDUCE/EXIT 信号在连续 N 个周期均被创建但未平仓，
    发出 False-Hold 告警并为信号写入 false_hold_protection=True 元数据
  - V11 主开关（SELF_PERCEPTION_V1101_ENABLED）控制告警逻辑启用

与 PositionMonitor 的区别：
  - PositionMonitor：触发止损/止盈/超龄的「硬性」出场
  - PositionRebalanceMonitor：将 AI 评分给出的「软性」减仓/卖出建议转为信号

调用时机：
  - 由 quant_loop_jobs.run_position_rebalance_scan() 每小时触发
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.position_score import PositionScore
from app.models.trading_signal import (
    SignalSource,
    SignalStatus,
    SignalType,
    TradingSignal,
)

logger = logging.getLogger(__name__)

# 评分建议阈值
_SCORE_REDUCE_THRESHOLD = 54  # overall_score <= 54 → REDUCE
_SCORE_SELL_THRESHOLD = 39  # overall_score <= 39 → EXIT/SELL

# 减仓默认比例（30% of current position）
_DEFAULT_REDUCE_RATIO = 0.30

# 评分有效期（超过此时间的评分不参考）
_SCORE_VALID_HOURS = 24

_RECOMMENDATION_RANK = {
    "SELL": 0,
    "REDUCE": 1,
    "HOLD": 2,
    "BUY": 3,
    "STRONG_BUY": 4,
}

_RISK_LEVEL_RANK = {
    "EXTREME": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
}


def _coerce_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PositionRebalanceMonitor:
    """
    持仓再平衡监控器

    将 PositionScoringService 生成的 REDUCE/SELL 建议转化为
    TradingSignal，以便 AutonomousEngine 和 OrderExecutor 执行。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _empty_scan_result(scanned: int = 0) -> Dict[str, Any]:
        return {
            "scanned": scanned,
            "reduce_signals": 0,
            "exit_signals": 0,
            "skipped_no_score": 0,
            "skipped_already_pending": 0,
            "details": [],
        }

    @staticmethod
    def _merge_scan_outcome(
        summary: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> None:
        for key in (
            "reduce_signals",
            "exit_signals",
            "skipped_no_score",
            "skipped_already_pending",
        ):
            summary[key] += int(outcome.get(key, 0))
        detail = outcome.get("detail")
        if detail is not None:
            summary["details"].append(detail)

    @staticmethod
    def _extract_score_snapshot(
        score_record: PositionScore,
    ) -> tuple[str, int]:
        recommendation = str(
            getattr(score_record, "recommendation", "HOLD") or "HOLD"
        ).upper()
        overall_val = getattr(score_record, "overall_score", 50)
        overall = int(overall_val) if overall_val is not None else 50
        return recommendation, overall

    @staticmethod
    def _resolve_signal_plan(
        recommendation: str,
        overall: int,
        qty: float,
    ) -> tuple[SignalType, float, int]:
        if recommendation == "SELL" or overall <= _SCORE_SELL_THRESHOLD:
            return SignalType.EXIT, abs(qty), 85
        quantity = max(1.0, abs(qty) * _DEFAULT_REDUCE_RATIO)
        return SignalType.REDUCE, quantity, 65

    async def scan(self, account_id: str) -> Dict[str, Any]:
        """
        主入口：扫描所有持仓的最新评分，按建议创建信号。

        Returns:
            {
                "scanned": int,
                "reduce_signals": int,
                "exit_signals": int,
                "skipped_no_score": int,
                "skipped_already_pending": int,
                "details": [...]
            }
        """
        positions = await self._fetch_positions(account_id)
        if not positions:
            return self._empty_scan_result()

        summary = self._empty_scan_result(scanned=len(positions))

        for pos in positions:
            self._merge_scan_outcome(
                summary,
                await self._process_position(account_id, pos),
            )

        await self._commit_changes("[RebalanceMonitor]")
        return summary

    async def enforce_position_capacity(
        self,
        account_id: str,
        *,
        max_positions: int,
        force_refresh_scores: bool = True,
    ) -> Dict[str, Any]:
        """当持仓标的数超过上限时，按最弱持仓优先生成 EXIT 信号，主动降载。"""
        positions = await self._fetch_positions(account_id)
        current_positions = len(positions)

        if max_positions <= 0:
            logger.warning(
                "[CapacityGuard] invalid max_positions=%s, skip", max_positions
            )
            return {
                "current_positions": current_positions,
                "max_positions": max_positions,
                "overflow": 0,
                "pending_exit_symbols": [],
                "created_exit_signals": 0,
                "details": [],
                "status": "invalid-config",
            }

        if current_positions <= max_positions:
            return {
                "current_positions": current_positions,
                "max_positions": max_positions,
                "overflow": 0,
                "pending_exit_symbols": [],
                "created_exit_signals": 0,
                "details": [],
                "status": "within-limit",
            }

        pending_exit_symbols = await self._get_pending_exit_symbols(account_id)
        symbols_in_position = {str(p["symbol"]).upper() for p in positions}
        pending_exit_symbols = {
            s for s in pending_exit_symbols if s in symbols_in_position
        }
        effective_overflow = max(
            0, current_positions - max_positions - len(pending_exit_symbols)
        )

        if effective_overflow <= 0:
            return {
                "current_positions": current_positions,
                "max_positions": max_positions,
                "overflow": current_positions - max_positions,
                "pending_exit_symbols": sorted(pending_exit_symbols),
                "created_exit_signals": 0,
                "details": [],
                "status": "pending-exits-sufficient",
            }

        candidates = await self._build_capacity_candidates(
            account_id,
            positions,
            force_refresh_scores=force_refresh_scores,
        )
        candidates = [c for c in candidates if c["symbol"] not in pending_exit_symbols]
        candidates.sort(key=self._capacity_candidate_sort_key)

        created = 0
        details: List[Dict[str, Any]] = []

        for candidate in candidates[:effective_overflow]:
            symbol = candidate["symbol"]
            qty = float(candidate["qty"])
            quantity = abs(qty)
            note_reason = (
                f"超出最大并发持仓上限：当前 {current_positions} 个 > "
                f"上限 {max_positions} 个；基于持仓评估自动腾挪仓位"
                f"（score={candidate['overall_score']}, "
                f"rec={candidate['recommendation']}）"
            )
            self._create_signal(
                account_id=account_id,
                symbol=symbol,
                qty=qty,
                quantity=quantity,
                signal_type=SignalType.EXIT,
                score=int(candidate["overall_score"]),
                recommendation=str(candidate["recommendation"]),
                priority=92,
                note_reason=note_reason,
                metadata_extra={
                    "capacity_guard": True,
                    "capacity_guard_overflow": (current_positions - max_positions),
                    "capacity_guard_target_max": max_positions,
                    "capacity_guard_rank": created + 1,
                    "risk_level": candidate.get("risk_level"),
                    "target_position": candidate.get("target_position"),
                    "last_price": candidate.get("last_price"),
                },
            )
            created += 1
            details.append(
                {
                    "symbol": symbol,
                    "score": candidate["overall_score"],
                    "recommendation": candidate["recommendation"],
                    "risk_level": candidate.get("risk_level"),
                    "target_position": candidate.get("target_position"),
                    "signal_created": SignalType.EXIT.value,
                }
            )

        await self._commit_changes("[CapacityGuard]", raise_on_error=True)

        return {
            "current_positions": current_positions,
            "max_positions": max_positions,
            "overflow": current_positions - max_positions,
            "pending_exit_symbols": sorted(pending_exit_symbols),
            "created_exit_signals": created,
            "details": details,
            "status": "capacity-reduced",
        }

    async def _process_position(
        self,
        account_id: str,
        pos: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = str(pos["symbol"])
        qty = float(pos["qty"])
        if qty == 0:
            return {}

        score_record = await self._get_latest_score(account_id, symbol)
        if score_record is None:
            logger.debug(
                "[RebalanceMonitor] %s: no recent score, skip",
                symbol,
            )
            return {"skipped_no_score": 1}

        recommendation, overall = self._extract_score_snapshot(score_record)
        if recommendation not in ("REDUCE", "SELL"):
            return {
                "detail": {
                    "symbol": symbol,
                    "score": overall,
                    "recommendation": recommendation,
                    "signal_created": None,
                }
            }

        if await self._has_pending_signal(account_id, symbol):
            logger.debug(
                "[RebalanceMonitor] %s: pending signal already exists, skip",
                symbol,
            )
            return {
                "skipped_already_pending": 1,
                "detail": {
                    "symbol": symbol,
                    "score": overall,
                    "recommendation": recommendation,
                    "signal_created": "SKIPPED_PENDING",
                },
            }

        signal_type, quantity, priority = self._resolve_signal_plan(
            recommendation,
            overall,
            qty,
        )
        false_hold = await self._should_flag_false_hold(
            account_id,
            symbol,
            score=overall,
            recommendation=recommendation,
        )

        self._create_signal(
            account_id=account_id,
            symbol=symbol,
            qty=qty,
            quantity=quantity,
            signal_type=signal_type,
            score=overall,
            recommendation=recommendation,
            priority=priority,
            false_hold_protection=false_hold,
        )
        logger.info(
            "[RebalanceMonitor] %s signal created: %s score=%s qty=%.0f",
            signal_type.value,
            symbol,
            overall,
            quantity,
        )
        return {
            "reduce_signals": int(signal_type == SignalType.REDUCE),
            "exit_signals": int(signal_type == SignalType.EXIT),
            "detail": {
                "symbol": symbol,
                "score": overall,
                "recommendation": recommendation,
                "signal_created": signal_type.value,
                "quantity": quantity,
            },
        }

    async def _commit_changes(
        self,
        log_prefix: str,
        *,
        raise_on_error: bool = False,
    ) -> None:
        try:
            await self.session.commit()
        except SQLAlchemyError as exc:
            logger.error("%s DB commit failed: %s", log_prefix, exc)
            await self.session.rollback()
            if raise_on_error:
                raise

    async def _should_flag_false_hold(
        self,
        account_id: str,
        symbol: str,
        *,
        score: int,
        recommendation: str,
    ) -> bool:
        if not getattr(settings, "SELF_PERCEPTION_V1101_ENABLED", False):
            return False

        threshold_rounds = int(getattr(settings, "FALSE_HOLD_DETECTION_ROUNDS", 3))
        cycle_count = await self._count_recent_reduce_signals(
            account_id,
            symbol,
            hours=48,
        )
        if cycle_count < threshold_rounds:
            return False
        await self._emit_false_hold_alert(
            account_id,
            symbol,
            score=score,
            recommendation=recommendation,
            cycle_count=cycle_count,
        )
        return True

    @staticmethod
    def _normalize_position(position: Any) -> Dict[str, Any] | None:
        symbol = getattr(position, "symbol", None) or (
            position.get("symbol") if isinstance(position, dict) else None
        )
        qty = getattr(position, "quantity", None) or (
            (position.get("quantity") or position.get("qty"))
            if isinstance(position, dict)
            else None
        )
        last_price = getattr(position, "last_price", None) or (
            position.get("last_price") if isinstance(position, dict) else None
        )
        avg_price = getattr(position, "avg_price", None) or (
            position.get("avg_price") if isinstance(position, dict) else None
        )
        parsed_qty = _coerce_optional_float(qty)
        if not symbol or parsed_qty in (None, 0.0):
            return None
        return {
            "symbol": str(symbol).strip().upper(),
            "qty": parsed_qty,
            "last_price": _coerce_optional_float(last_price),
            "avg_price": _coerce_optional_float(avg_price),
        }

    async def _fetch_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """从 Broker 拉取当前持仓"""
        try:
            from app.broker.dummy_option_client import DummyOptionClient
            from app.broker.factory import make_option_broker_client

            broker = make_option_broker_client()
            if isinstance(broker, DummyOptionClient):
                logger.debug("[RebalanceMonitor] DummyClient — 跳过持仓拉取")
                return []

            raw = await broker.list_underlying_positions(account_id)
            positions: List[Dict[str, Any]] = []
            for raw_position in raw:
                normalized = self._normalize_position(raw_position)
                if normalized is not None:
                    positions.append(normalized)
            return positions
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            logger.error("[RebalanceMonitor] 持仓拉取失败: %s", exc)
            return []

    async def _get_latest_score(
        self, account_id: str, symbol: str
    ) -> Optional[PositionScore]:
        """获取 24h 内最新的持仓评分"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_SCORE_VALID_HOURS)
        stmt = (
            select(PositionScore)
            .where(
                and_(
                    or_(
                        PositionScore.account_id == account_id,
                        PositionScore.account_id == "DEMO",  # 兼容默认 account_id
                    ),
                    PositionScore.symbol == symbol,
                    PositionScore.timestamp >= cutoff,
                )
            )
            .order_by(desc(PositionScore.timestamp))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _has_pending_signal(self, account_id: str, symbol: str) -> bool:
        """检查是否已有待执行的 REDUCE / EXIT 信号"""
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.symbol == symbol,
                TradingSignal.signal_type.in_([SignalType.REDUCE, SignalType.EXIT]),
                TradingSignal.status.in_(
                    [
                        SignalStatus.GENERATED,
                        SignalStatus.VALIDATED,
                        SignalStatus.QUEUED,
                        SignalStatus.EXECUTING,
                    ]
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def _get_pending_exit_symbols(self, account_id: str) -> set[str]:
        """获取已有待执行 EXIT 信号的标的集合。"""
        stmt = select(TradingSignal.symbol).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.signal_type == SignalType.EXIT,
                TradingSignal.status.in_(
                    [
                        SignalStatus.GENERATED,
                        SignalStatus.VALIDATED,
                        SignalStatus.QUEUED,
                        SignalStatus.EXECUTING,
                    ]
                ),
            )
        )
        result = await self.session.execute(stmt)
        return {str(row[0]).upper() for row in result.all() if row and row[0]}

    async def _build_capacity_candidates(
        self,
        account_id: str,
        positions: List[Dict[str, Any]],
        *,
        force_refresh_scores: bool,
    ) -> List[Dict[str, Any]]:
        """构建超并发持仓降载候选：优先使用最新持仓评分与建议。"""
        from app.services.position_scoring_service import PositionScoringService

        scorer = PositionScoringService()
        candidates: List[Dict[str, Any]] = []

        for pos in positions:
            symbol = str(pos["symbol"]).upper()
            last_price = pos.get("last_price")
            score_obj = await scorer.calculate_position_score(
                symbol=symbol,
                current_price=last_price,
                force_refresh=force_refresh_scores,
            )
            if score_obj is None:
                score_obj = await self._get_latest_score(account_id, symbol)

            recommendation = str(
                getattr(score_obj, "recommendation", "HOLD") or "HOLD"
            ).upper()
            overall_score_val = getattr(score_obj, "overall_score", 50)
            if score_obj is None:
                overall_score_val = 50
            overall_score = (
                int(overall_score_val) if overall_score_val is not None else 50
            )

            candidates.append(
                {
                    "symbol": symbol,
                    "qty": float(pos["qty"]),
                    "last_price": last_price,
                    "recommendation": recommendation,
                    "overall_score": overall_score,
                    "risk_level": getattr(score_obj, "risk_level", None),
                    "target_position": getattr(
                        score_obj,
                        "target_position",
                        None,
                    ),
                }
            )

        return candidates

    @staticmethod
    def _capacity_candidate_sort_key(candidate: Dict[str, Any]) -> tuple:
        recommendation = str(candidate.get("recommendation") or "HOLD").upper()
        risk_level = str(candidate.get("risk_level") or "MEDIUM").upper()
        target_position = candidate.get("target_position")
        if target_position is None:
            target_position = 0.5

        return (
            _RECOMMENDATION_RANK.get(recommendation, 99),
            int(candidate.get("overall_score") or 50),
            _RISK_LEVEL_RANK.get(risk_level, 99),
            float(target_position),
            str(candidate.get("symbol") or ""),
        )

    def _create_signal(
        self,
        account_id: str,
        symbol: str,
        qty: float,
        quantity: float,
        signal_type: SignalType,
        score: int,
        recommendation: str,
        priority: int,
        note_reason: Optional[str] = None,
        metadata_extra: Optional[Dict[str, Any]] = None,
        false_hold_protection: bool = False,
    ) -> TradingSignal:
        """创建 REDUCE / EXIT TradingSignal"""
        direction = "LONG" if qty > 0 else "SHORT"

        notes = note_reason or (
            f"AI 评分 {score}/100 (建议: {recommendation}) — "
            f"由 PositionRebalanceMonitor 自动生成"
        )

        metadata: Dict[str, Any] = {
            "closing_intent": signal_type.value,
            "execution_path": "FAST_CLOSE",
            "generated_by": "PositionRebalanceMonitor",
            "recommendation": recommendation,
            "current_position": {
                "qty": abs(qty),
                "price": None,
            },
        }
        if false_hold_protection:
            metadata["false_hold_protection"] = True
            metadata["funnel_bypass"] = "is_closing_fast_path"
        if metadata_extra:
            metadata.update(metadata_extra)

        signal = TradingSignal(
            signal_id=str(uuid4()),
            account_id=account_id,
            user_id=account_id,
            symbol=symbol,
            signal_type=signal_type,
            signal_source=SignalSource.RISK_MGMT,
            status=SignalStatus.GENERATED,
            direction=direction,
            quantity_mode="ABS_SHARES",
            quantity_value=quantity,
            suggested_quantity=quantity,
            signal_strength=max(0.1, (100 - score) / 100),
            confidence=max(0.1, (100 - score) / 100),
            risk_score=(100 - score) / 100,
            priority=priority,
            notes=notes,
            max_holding_days=None,
            created_at=datetime.now(timezone.utc),
            extra_metadata=metadata,
        )
        self.session.add(signal)
        return signal

    async def _count_recent_reduce_signals(
        self,
        account_id: str,
        symbol: str,
        *,
        hours: int = 48,
    ) -> int:
        """查询近 N 小时内为该标的创建的 REDUCE/EXIT 信号数量。"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.symbol == symbol,
                TradingSignal.signal_type.in_([SignalType.REDUCE, SignalType.EXIT]),
                TradingSignal.signal_source == SignalSource.RISK_MGMT,
                TradingSignal.created_at >= cutoff,
            )
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def _emit_false_hold_alert(
        self,
        account_id: str,
        symbol: str,
        *,
        score: int,
        recommendation: str,
        cycle_count: int,
    ) -> None:
        """将 False-Hold 告警写入 Redis（MetaStateSnapshotService 消费）。"""
        try:
            from app.models.db import redis_client as _redis

            if _redis is None:
                return
            import json as _json

            key = f"false_hold_alert:{account_id}:{symbol}"
            alert = {
                "account_id": account_id,
                "symbol": symbol,
                "score": score,
                "recommendation": recommendation,
                "reduce_cycle_count": cycle_count,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            await _redis.set(key, _json.dumps(alert), ex=86400)
            message = (
                "[RebalanceMonitor] False-Hold alert emitted: %s " "score=%d cycles=%d"
            )
            logger.info(
                message,
                symbol,
                score,
                cycle_count,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            logger.debug(
                "[RebalanceMonitor] _emit_false_hold_alert skipped: %s",
                exc,
            )
