"""V10.5.2: CapacityArbiterService — 席位竞争仲裁引擎

核心职责：
  当持仓数达到或超过上限，且有新开仓信号到达时，不再直接拒绝信号。
  而是将"当前持仓 + 新信号"统一纳入候选池，按统一准入分进行排序，
  淘汰末尾 N 个对象（N = 持仓数 + 信号数 - 上限）。
    - 被淘汰的持仓 → 生成 EXIT 信号并加入执行队列
    - 被淘汰的信号 → 标记为 SEAT_COMPETITION_ELIMINATED 并拒绝

使用保护带防止频繁换仓：
  - MIN_REPLACEMENT_EDGE     : 挑战者比末位持仓高出 X 分才触发替换
  - MAX_REPLACEMENTS_PER_CYCLE: 单次决策周期最多替换席位数
  - CAPACITY_MIN_HOLD_MINUTES: 持仓建立后 X 分钟内免疫竞争
  - REPLACEMENT_COOLDOWN     : 同一持仓被替换后 X 分钟内不再参与竞争
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── 候选类型常量 ─────────────────────────────────────────────────────────────
CANDIDATE_POSITION = "POSITION"
CANDIDATE_SIGNAL = "SIGNAL"


@dataclass
class CapacityCandidate:
    """统一候选池条目：可以是当前持仓或新开仓信号。"""

    candidate_type: str  # POSITION | SIGNAL
    symbol: str

    # ── 原始分数 ──
    raw_score: float  # 0~100；持仓用 overall_score，信号用 conviction_score
    admission_score: float = 0.0  # 最终排序用的综合准入分（含衰减、摩擦扣分等）

    # ── 持仓专属 ──
    position_id: Optional[int] = None
    hold_minutes: float = 0.0  # 已持有分钟数
    recommendation: str = "HOLD"
    is_protected: bool = False  # 因最小持有时间或冷却保护而豁免竞争
    protect_reason: Optional[str] = None

    # ── 信号专属 ──
    signal_id: Optional[int] = None
    signal_dict: Optional[dict] = None  # 原始信号 dict，用于后续处理

    # ── 用于日志 ──
    rank: int = 0
    eliminate: bool = False
    eliminated_reason: Optional[str] = None

    # ── V10.5.3: Portfolio Construction 2.1 可解释字段 ──
    seat_value: float = 0.0
    marginal_alpha: float = 0.0
    marginal_risk: float = 0.0
    marginal_turnover: float = 0.0
    liquidity_usage: float = 0.0
    replace_or_hold_reason: Optional[str] = None

    def as_snapshot_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "type": self.candidate_type,
            "candidate_type": self.candidate_type,
            "raw_score": round(self.raw_score, 2),
            "admission_score": round(self.admission_score, 2),
            "protected": self.is_protected,
            "is_protected": self.is_protected,
            "protect_reason": self.protect_reason,
            "hold_minutes": (
                round(self.hold_minutes, 2)
                if self.candidate_type == CANDIDATE_POSITION
                else None
            ),
            "recommendation": (
                self.recommendation
                if self.candidate_type == CANDIDATE_POSITION
                else None
            ),
            "signal_id": self.signal_id,
            "rank": self.rank,
            "eliminate": self.eliminate,
            "eliminated_reason": self.eliminated_reason,
            "seat_value": round(self.seat_value, 2),
            "marginal_alpha": round(self.marginal_alpha, 4),
            "marginal_risk": round(self.marginal_risk, 4),
            "marginal_turnover": round(self.marginal_turnover, 4),
            "liquidity_usage": round(self.liquidity_usage, 4),
            "replace_or_hold_reason": self.replace_or_hold_reason,
        }


@dataclass
class ArbiterDecision:
    """
    仲裁决策结果，由 CapacityArbiterService.evaluate() 返回。
    """

    # 已通过竞争，可继续推进执行的信号列表（subset of input signals）
    approved_signals: List[dict] = field(default_factory=list)

    # 在竞争中被淘汰、应被拒绝的信号列表
    rejected_signals: List[dict] = field(default_factory=list)

    # 需要被平仓的持仓 symbol 列表
    positions_to_close: List[str] = field(default_factory=list)

    # EXIT 信号已创建成功的 symbol 列表（subset of positions_to_close）
    exit_signals_created: List[str] = field(default_factory=list)

    # 候选池快照（用于审计日志）
    candidates_snapshot: List[dict] = field(default_factory=list)

    # 统计摘要
    overflow: int = 0
    max_positions: int = 0
    positions_count: int = 0
    signals_count: int = 0
    min_edge_protected: int = 0
    cooldown_protected: int = 0
    min_hold_protected: int = 0
    max_replacements_cap: int = 0
    replacement_triggered: bool = False
    dry_run: bool = False

    cycle_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class CapacityArbiterService:
    """
    席位竞争仲裁服务。

    usage::

        arbiter = CapacityArbiterService()
        decision = await arbiter.evaluate(
            account_id="DU123",
            current_positions=positions_snapshot,  # dict from PositionMonitor
            entry_signals=pending_signals,          # list of signal dicts (ENTRY类型)
            max_positions=6,
            regime="BULL_TREND",
            db=db,
        )
        # decision.approved_signals  → 继续走 quality funnel
        # decision.rejected_signals  → 直接标记 REJECTED
        # decision.positions_to_close → EXIT 信号已生成
    """

    async def evaluate(
        self,
        *,
        account_id: str,
        current_positions: Dict[str, Any],  # {symbol: {qty, avg_cost, ...}}
        entry_signals: List[dict],  # 待处理 ENTRY 信号列表
        max_positions: int,
        regime: str,
        db: AsyncSession,
        cycle_id: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> ArbiterDecision:
        """
        执行席位竞争仲裁。

        Returns ArbiterDecision with approved/rejected signals and positions to close.
        """
        from app.services.signal_quality_config import \
            get_signal_quality_config

        cfg = get_signal_quality_config()

        # dry_run 优先使用显式参数，否则使用配置
        _dry_run = (
            dry_run
            if dry_run is not None
            else cfg.CAPACITY_REPLACEMENT_DRY_RUN
        )

        if not cfg.CAPACITY_REPLACEMENT_ENABLED:
            # 功能关闭 → 所有信号不参与竞争，全部通过（Layer 2 硬拒逻辑仍生效）
            logger.debug("[CapacityArbiter] Feature disabled, all signals pass through")
            return ArbiterDecision(
                approved_signals=entry_signals,
                max_positions=max_positions,
                positions_count=len(current_positions),
                signals_count=len(entry_signals),
                dry_run=_dry_run,
                cycle_id=cycle_id or str(uuid.uuid4()),
            )

        positions_count = len(current_positions)
        signals_count = len(entry_signals)
        total_candidates = positions_count + signals_count
        overflow = max(0, total_candidates - max_positions)

        _cycle_id = cycle_id or str(uuid.uuid4())

        if overflow <= 0:
            # 候选池未超出上限，无需竞争
            return ArbiterDecision(
                approved_signals=entry_signals,
                max_positions=max_positions,
                positions_count=positions_count,
                signals_count=signals_count,
                overflow=0,
                dry_run=_dry_run,
                cycle_id=_cycle_id,
            )

        logger.info(
            "[CapacityArbiter] Overflow=%d (positions=%d + signals=%d > max=%d), "
            "starting seat competition [cycle=%s]",
            overflow,
            positions_count,
            signals_count,
            max_positions,
            _cycle_id,
        )

        # ── 1. 构建候选池 ────────────────────────────────────────────────────
        position_candidates = await self._build_position_candidates(
            account_id=account_id,
            current_positions=current_positions,
            db=db,
            cfg=cfg,
        )
        signal_candidates = await self._build_signal_candidates(
            entry_signals=entry_signals,
            regime=regime,
        )

        candidates = position_candidates + signal_candidates

        # ── 2. 按 admission_score 降序排列 ──────────────────────────────────
        #    受保护的持仓强制排在前面（不参与末尾淘汰）
        protected = [c for c in candidates if c.is_protected]
        unprotected = [c for c in candidates if not c.is_protected]
        unprotected.sort(
            key=self._candidate_rank_score,
            reverse=True,
        )

        # 合并：受保护排在最前（视为"已安全"）
        candidates = protected + unprotected

        for idx, c in enumerate(candidates, start=1):
            c.rank = idx

        # ── 3. 淘汰末位 overflow 个非受保护对象 ──────────────────────────────
        decision = ArbiterDecision(
            overflow=overflow,
            max_positions=max_positions,
            positions_count=positions_count,
            signals_count=signals_count,
            dry_run=_dry_run,
            cycle_id=_cycle_id,
            min_hold_protected=sum(
                1 for c in candidates if c.protect_reason == "min_hold"
            ),
            cooldown_protected=sum(
                1 for c in candidates if c.protect_reason == "cooldown"
            ),
        )

        # 只从非受保护的对象中淘汰
        to_eliminate_pool = [
            c for c in unprotected if c.candidate_type == CANDIDATE_POSITION
        ] + [c for c in unprotected if c.candidate_type == CANDIDATE_SIGNAL]
        # 重新排 admission_score 从低到高（候选末尾 = 得分最低）
        to_eliminate_pool.sort(key=self._candidate_rank_score)

        min_edge = cfg.CAPACITY_REPLACEMENT_MIN_EDGE
        max_replace = cfg.CAPACITY_REPLACEMENT_MAX_PER_CYCLE
        replace_count = 0

        positions_to_close: List[str] = []
        rejected_signals: List[dict] = []
        remaining_overflow = overflow
        for candidate in to_eliminate_pool:
            if remaining_overflow <= 0:
                break

            if candidate.candidate_type == CANDIDATE_POSITION:
                # 保护带：挑战者必须比末位持仓得分领先 min_edge 才允许替换
                # 找当前候选池中得分最高的信号进行比较
                best_signal_score = max(
                    (
                        self._candidate_rank_score(c)
                        for c in signal_candidates
                        if not c.is_protected
                    ),
                    default=0.0,
                )
                edge = best_signal_score - self._candidate_rank_score(candidate)
                if edge < min_edge:
                    candidate.is_protected = True
                    candidate.protect_reason = "min_edge"
                    candidate.replace_or_hold_reason = "MIN_EDGE_PROTECTED"
                    decision.min_edge_protected += 1
                    logger.debug(
                        "[CapacityArbiter] Position %s protected by min_edge (edge=%.1f < %.1f)",
                        candidate.symbol,
                        edge,
                        min_edge,
                    )
                    # 此时无法替换该持仓，找下一个信号候选代替淘汰
                    remaining_overflow -= 1  # 该席位维持持仓，对应那个信号候选必须被拒
                    # 找得分最低的信号候选淘汰
                    worst_signal = next(
                        (
                            c
                            for c in to_eliminate_pool
                            if c.candidate_type == CANDIDATE_SIGNAL and not c.eliminate
                        ),
                        None,
                    )
                    if worst_signal:
                        worst_signal.eliminate = True
                        worst_signal.eliminated_reason = (
                            "seat_competition_signal_eliminated"
                        )
                        worst_signal.replace_or_hold_reason = (
                            "REJECTED_BY_MIN_EDGE"
                        )
                        rejected_signals.append(worst_signal.signal_dict or {})
                    continue

                if replace_count >= max_replace:
                    decision.max_replacements_cap += 1
                    logger.debug(
                        "[CapacityArbiter] Max replacements (%d) reached, "
                        "marking signal as rejected instead",
                        max_replace,
                    )
                    remaining_overflow -= 1
                    worst_signal = next(
                        (
                            c
                            for c in to_eliminate_pool
                            if c.candidate_type == CANDIDATE_SIGNAL and not c.eliminate
                        ),
                        None,
                    )
                    if worst_signal:
                        worst_signal.eliminate = True
                        worst_signal.eliminated_reason = "max_replacements_cap"
                        worst_signal.replace_or_hold_reason = (
                            "REJECTED_BY_MAX_REPLACEMENTS_CAP"
                        )
                        rejected_signals.append(worst_signal.signal_dict or {})
                    continue

                candidate.eliminate = True
                candidate.eliminated_reason = "seat_competition_position_eliminated"
                candidate.replace_or_hold_reason = "REPLACED_BY_CHALLENGER"
                positions_to_close.append(candidate.symbol)
                replace_count += 1
                remaining_overflow -= 1

            else:  # CANDIDATE_SIGNAL
                if candidate.eliminate:
                    # 已被上面的 worst_signal 逻辑标记
                    remaining_overflow -= 1
                    continue
                candidate.eliminate = True
                candidate.eliminated_reason = "seat_competition_signal_eliminated"
                candidate.replace_or_hold_reason = "SIGNAL_ELIMINATED"
                rejected_signals.append(candidate.signal_dict or {})
                remaining_overflow -= 1

        # ── 4. 确定通过竞争的信号 ──────────────────────────────────────────
        eliminated_signal_ids = {
            c.signal_id
            for c in signal_candidates
            if c.eliminate and c.signal_id is not None
        }
        eliminated_symbols = {c.symbol for c in signal_candidates if c.eliminate}
        approved_signals = [
            sig
            for sig in entry_signals
            if (
                sig.get("id") not in eliminated_signal_ids
                and sig.get("symbol") not in eliminated_symbols
            )
        ]

        decision.approved_signals = approved_signals
        decision.rejected_signals = rejected_signals
        decision.positions_to_close = positions_to_close
        decision.replacement_triggered = len(positions_to_close) > 0
        decision.candidates_snapshot = [c.as_snapshot_dict() for c in candidates]

        # ── 5. 生成平仓信号（非 dry_run 时）──────────────────────────────────
        if positions_to_close and not _dry_run:
            exit_created = await self._create_exit_signals(
                account_id=account_id,
                symbols_to_close=positions_to_close,
                position_candidates=position_candidates,
                cycle_id=_cycle_id,
                db=db,
            )
            decision.exit_signals_created = exit_created
            # P1.4: 已触发席位替换，审计批准的 ENTRY 信号应在 EXIT 信号完成后才执行。
            # 在批准信号元数据中记录待完成的 EXIT 符号，供 AutonomousEngine 进行顺序校验。
            if exit_created:
                logger.warning(
                    "[CapacityArbiter][P1.4] Displacement detected: %d EXIT signal(s) queued "
                    "for symbols=%s [cycle=%s]. Approved ENTRY signals should defer execution "
                    "until EXIT completion.",
                    len(exit_created),
                    exit_created,
                    _cycle_id,
                )
                for sig in approved_signals:
                    sig_meta = sig.get("extra_metadata") if isinstance(sig, dict) else None
                    if isinstance(sig_meta, dict):
                        sig_meta["displacement_pending_exit_symbols"] = exit_created
                        sig_meta["displacement_cycle_id"] = _cycle_id
        elif positions_to_close and _dry_run:
            logger.info(
                "[CapacityArbiter] DRY-RUN: would close positions %s",
                positions_to_close,
            )
            decision.exit_signals_created = []

        # ── 6. 写容量决策日志 ─────────────────────────────────────────────
        await self._write_capacity_log(
            account_id=account_id,
            regime=regime,
            decision=decision,
            db=db,
        )

        logger.info(
            "[CapacityArbiter] Seat competition complete: "
            "approved=%d, rejected=%d, positions_to_close=%d [cycle=%s]",
            len(approved_signals),
            len(rejected_signals),
            len(positions_to_close),
            _cycle_id,
        )
        return decision

    # ─────────────────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────────────────

    async def _build_position_candidates(
        self,
        *,
        account_id: str,
        current_positions: Dict[str, Any],
        db: AsyncSession,
        cfg: Any,
    ) -> List[CapacityCandidate]:
        """为每个当前持仓构建 CapacityCandidate，带评分与保护判断。"""
        from sqlalchemy import and_, desc, select

        from app.models.position import Position, PositionStatus
        from app.models.position_score import PositionScore

        now = datetime.now(timezone.utc)
        min_hold = timedelta(minutes=cfg.CAPACITY_MIN_HOLD_MINUTES)
        cooldown = timedelta(minutes=cfg.CAPACITY_REPLACEMENT_COOLDOWN_MINUTES)

        # 批量查最新 PositionScore
        symbols = list(current_positions.keys())
        score_map: Dict[str, PositionScore] = {}
        if symbols:
            try:
                stmt = (
                    select(PositionScore)
                    .where(PositionScore.symbol.in_(symbols))
                    .order_by(PositionScore.timestamp.desc())
                )
                result = await db.execute(stmt)
                for row in result.scalars().all():
                    if row.symbol not in score_map:
                        score_map[row.symbol] = row
            except Exception as e:
                logger.warning(
                    "[CapacityArbiter] Failed to load position scores: %s", e
                )

        # 批量查 lifecycle 持仓时间，避免仅用最近 PositionScore.timestamp
        # 误判老仓位为“刚开仓”，从而把所有席位都套上 min_hold 保护。
        lifecycle_opened_at: Dict[str, datetime] = {}
        if symbols:
            try:
                pos_stmt = (
                    select(Position)
                    .where(
                        Position.account_id == account_id,
                        Position.symbol.in_(symbols),
                        Position.status.in_(
                            [
                                PositionStatus.PENDING.value,
                                PositionStatus.OPENING.value,
                                PositionStatus.ACTIVE.value,
                                PositionStatus.SCALING_IN.value,
                                PositionStatus.SCALING_OUT.value,
                                PositionStatus.CLOSING.value,
                                PositionStatus.PARTIALLY_CLOSED.value,
                                PositionStatus.EXCEPTION.value,
                            ]
                        ),
                    )
                    .order_by(Position.opened_at.is_(None), Position.opened_at.asc(), Position.id.asc())
                )
                pos_result = await db.execute(pos_stmt)
                for row in pos_result.scalars().all():
                    symbol = str(row.symbol or "").upper()
                    if symbol and symbol not in lifecycle_opened_at and row.opened_at:
                        opened_at = row.opened_at
                        if opened_at.tzinfo is None:
                            opened_at = opened_at.replace(tzinfo=timezone.utc)
                        lifecycle_opened_at[symbol] = opened_at
            except Exception as e:
                logger.warning(
                    "[CapacityArbiter] Failed to load lifecycle opened_at timestamps: %s",
                    e,
                )

        # 查替换冷却记录（最近被平仓的持仓，检查 cooldown）
        cooldown_symbols: set = set()
        try:
            from app.models.capacity_decision_log import CapacityDecisionLog

            cutoff = now - cooldown
            stmt2 = (
                select(CapacityDecisionLog)
                .where(
                    and_(
                        CapacityDecisionLog.account_id == account_id,
                        CapacityDecisionLog.created_at >= cutoff,
                        CapacityDecisionLog.replacement_triggered.is_(True),
                    )
                )
                .order_by(CapacityDecisionLog.created_at.desc())
                .limit(20)
            )
            res2 = await db.execute(stmt2)
            for log_row in res2.scalars().all():
                eliminated = log_row.eliminated_positions or []
                for item in eliminated:
                    if isinstance(item, dict):
                        cooldown_symbols.add(item.get("symbol", "").upper())
        except Exception as e:
            logger.debug("[CapacityArbiter] Cooldown check failed (non-fatal): %s", e)

        candidates: List[CapacityCandidate] = []
        for symbol, pos_data in current_positions.items():
            symbol_upper = str(symbol or "").upper()
            pos_score_obj = score_map.get(symbol)
            overall_score = (
                float(pos_score_obj.overall_score) if pos_score_obj else 50.0
            )
            recommendation = (
                str(pos_score_obj.recommendation) if pos_score_obj else "HOLD"
            )

            enriched_pos_data = dict(pos_data)
            lifecycle_open = lifecycle_opened_at.get(symbol_upper)
            if lifecycle_open and not (
                enriched_pos_data.get("opened_at") or enriched_pos_data.get("open_time")
            ):
                enriched_pos_data["opened_at"] = lifecycle_open

            # 持仓年龄：优先用 lifecycle opened_at，再回退到快照/score 时间
            hold_minutes = self._estimate_hold_minutes(
                enriched_pos_data, pos_score_obj, now
            )

            # 计算准入分（持仓扣摩擦罚分, 但 overall_score 是0~100）
            admission_score = self._position_admission_score(
                overall_score=overall_score,
                hold_minutes=hold_minutes,
                unrealized_pnl_pct=enriched_pos_data.get("unrealized_pnl_pct", 0.0),
            )

            # 保护判断
            is_protected = False
            protect_reason: Optional[str] = None
            if hold_minutes < cfg.CAPACITY_MIN_HOLD_MINUTES:
                is_protected = True
                protect_reason = "min_hold"
            elif symbol.upper() in cooldown_symbols:
                is_protected = True
                protect_reason = "cooldown"

            portfolio_metrics = self._build_portfolio_21_metrics(
                candidate_type=CANDIDATE_POSITION,
                raw_score=overall_score,
                admission_score=admission_score,
                hold_minutes=hold_minutes,
                unrealized_pnl_pct=float(
                    enriched_pos_data.get("unrealized_pnl_pct") or 0.0
                ),
                source_payload=enriched_pos_data,
            )

            candidates.append(
                CapacityCandidate(
                    candidate_type=CANDIDATE_POSITION,
                    symbol=symbol,
                    raw_score=overall_score,
                    admission_score=admission_score,
                    hold_minutes=hold_minutes,
                    recommendation=recommendation,
                    is_protected=is_protected,
                    protect_reason=protect_reason,
                    seat_value=portfolio_metrics["seat_value"],
                    marginal_alpha=portfolio_metrics["marginal_alpha"],
                    marginal_risk=portfolio_metrics["marginal_risk"],
                    marginal_turnover=portfolio_metrics["marginal_turnover"],
                    liquidity_usage=portfolio_metrics["liquidity_usage"],
                    replace_or_hold_reason=portfolio_metrics[
                        "replace_or_hold_reason"
                    ],
                )
            )

        return candidates

    async def _build_signal_candidates(
        self,
        *,
        entry_signals: List[dict],
        regime: str,
    ) -> List[CapacityCandidate]:
        """为每个待处理 ENTRY 信号构建 CapacityCandidate，使用 preview_quality 评分。"""
        from app.services.signal_quality_funnel import (SignalFunnelInput,
                                                        signal_quality_funnel)

        candidates: List[CapacityCandidate] = []
        for sig in entry_signals:
            signal_id = sig.get("id")
            symbol = str(sig.get("symbol") or "")

            # 构建 SignalFunnelInput，复用 AutonomousEngine 工具函数提取维度信息
            try:
                funnel_input = self._build_funnel_input_from_signal(sig, regime)
                profile = signal_quality_funnel.preview_quality(funnel_input)
                raw_score = float(profile.score)
            except Exception as e:
                logger.warning(
                    "[CapacityArbiter] preview_quality failed for signal %s/%s: %s, using 0",
                    signal_id,
                    symbol,
                    e,
                )
                raw_score = 0.0

            admission_score = self._signal_admission_score(raw_score)
            portfolio_metrics = self._build_portfolio_21_metrics(
                candidate_type=CANDIDATE_SIGNAL,
                raw_score=raw_score,
                admission_score=admission_score,
                source_payload=sig,
            )

            candidates.append(
                CapacityCandidate(
                    candidate_type=CANDIDATE_SIGNAL,
                    symbol=symbol,
                    raw_score=raw_score,
                    admission_score=admission_score,
                    signal_id=signal_id,
                    signal_dict=sig,
                    seat_value=portfolio_metrics["seat_value"],
                    marginal_alpha=portfolio_metrics["marginal_alpha"],
                    marginal_risk=portfolio_metrics["marginal_risk"],
                    marginal_turnover=portfolio_metrics["marginal_turnover"],
                    liquidity_usage=portfolio_metrics["liquidity_usage"],
                    replace_or_hold_reason=portfolio_metrics[
                        "replace_or_hold_reason"
                    ],
                )
            )

        return candidates

    @staticmethod
    def _clip_ratio(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _seat_value_arbiter_enabled() -> bool:
        return bool(settings.SEAT_VALUE_ARBITER_ENABLED)

    @classmethod
    def _candidate_rank_score(cls, candidate: CapacityCandidate) -> float:
        if cls._seat_value_arbiter_enabled():
            return float(candidate.seat_value)
        return float(candidate.admission_score)

    @classmethod
    def _estimate_liquidity_usage(
        cls,
        *,
        quantity: Any = None,
        price: Any = None,
        adv_usd: Any = None,
        default: float = 0.0,
    ) -> float:
        qty = abs(float(quantity or 0.0))
        px = abs(float(price or 0.0))
        adv = abs(float(adv_usd or 0.0))
        if qty > 0 and px > 0 and adv > 0:
            return cls._clip_ratio((qty * px) / adv)
        return cls._clip_ratio(default)

    @classmethod
    def _build_portfolio_21_metrics(
        cls,
        *,
        candidate_type: str,
        raw_score: float,
        admission_score: float,
        hold_minutes: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        source_payload: Optional[dict] = None,
    ) -> dict[str, float | str]:
        payload = source_payload or {}
        adv_usd = float(payload.get("adv_usd") or payload.get("avg_daily_volume") or 0.0)
        quantity = payload.get("quantity") or payload.get("qty") or payload.get("suggested_quantity")
        price = payload.get("current_price") or payload.get("avg_cost") or payload.get("suggested_price")

        marginal_alpha = cls._clip_ratio(raw_score / 100.0)
        marginal_risk = cls._clip_ratio((100.0 - admission_score) / 100.0)
        if candidate_type == CANDIDATE_SIGNAL:
            marginal_turnover = cls._clip_ratio(
                float(payload.get("quantity_value") or 0.25)
            )
            liquidity_usage = cls._estimate_liquidity_usage(
                quantity=quantity,
                price=price,
                adv_usd=adv_usd,
                default=0.25,
            )
            reason = (
                "REPLACE_CANDIDATE"
                if admission_score >= 60
                else "LOW_SEAT_VALUE"
            )
        else:
            marginal_turnover = cls._clip_ratio(min(0.15, hold_minutes / 28800.0))
            liquidity_usage = cls._estimate_liquidity_usage(
                quantity=quantity,
                price=price,
                adv_usd=adv_usd,
                default=0.10,
            )
            reason = "HOLD" if admission_score >= 60 else "REPLACEABLE"

        pnl_bonus = max(-5.0, min(5.0, float(unrealized_pnl_pct) * 5.0))
        seat_value = admission_score - marginal_turnover * 12 - liquidity_usage * 8
        seat_value = max(0.0, min(100.0, seat_value + pnl_bonus))

        return {
            "seat_value": seat_value,
            "marginal_alpha": marginal_alpha,
            "marginal_risk": marginal_risk,
            "marginal_turnover": marginal_turnover,
            "liquidity_usage": liquidity_usage,
            "replace_or_hold_reason": reason,
        }

    @staticmethod
    def _position_admission_score(
        overall_score: float,
        hold_minutes: float,
        unrealized_pnl_pct: float,
    ) -> float:
        """
        将持仓 overall_score（0~100）转化为统一量纲的准入分。
        衰减扣分：持有越久、亏损越多，准入分适当下降（体现机会成本）。
        公式（保守版）：
            admission = overall_score
                        - max(0, (hold_minutes - 480)) / 1440 * 3   # 超过8h后每天扣3分
                        + unrealized_pnl_pct * 10                    # 盈亏±10分内浮动
        结果 clip 到 [0, 100]。
        """
        score = overall_score
        # 持有衰减（超过 8h 后，每多持有 1 天扣 3 分，最多扣 15 分）
        decay = max(0.0, (hold_minutes - 480.0) / 1440.0) * 3.0
        score -= min(decay, 15.0)
        # 盈亏加成（盈利时小幅加分，亏损时扣分，上限 ±10）
        pnl_bonus = max(-10.0, min(10.0, float(unrealized_pnl_pct) * 10.0))
        score += pnl_bonus
        return max(0.0, min(100.0, score))

    @staticmethod
    def _signal_admission_score(conviction_score: float) -> float:
        """
        将 conviction_score（0~100）直接作为准入分。
        未来可加入相关性惩罚、预交易成本等。
        结果 clip 到 [0, 100]。
        """
        return max(0.0, min(100.0, float(conviction_score)))

    @staticmethod
    def _estimate_hold_minutes(
        pos_data: dict,
        pos_score_obj: Any,
        now: datetime,
    ) -> float:
        """
        估算持仓已持有分钟数。
        优先读 pos_data['opened_at']，其次 pos_score_obj.timestamp，再默认 0。
        """
        opened_at_raw = pos_data.get("opened_at") or pos_data.get("open_time")
        if opened_at_raw:
            try:
                if isinstance(opened_at_raw, str):
                    opened_at = datetime.fromisoformat(
                        opened_at_raw.replace("Z", "+00:00")
                    )
                elif isinstance(opened_at_raw, datetime):
                    opened_at = opened_at_raw
                else:
                    opened_at = None
                if opened_at:
                    if opened_at.tzinfo is None:
                        opened_at = opened_at.replace(tzinfo=timezone.utc)
                    return (now - opened_at).total_seconds() / 60.0
            except Exception:
                pass

        if pos_score_obj and pos_score_obj.timestamp:
            ts = pos_score_obj.timestamp
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return (now - ts).total_seconds() / 60.0

        # 无时间信息 → 保守视为长期持仓（不触发 min_hold 保护）
        return 9999.0

    @staticmethod
    def _build_funnel_input_from_signal(signal: dict, regime: str) -> Any:
        """从信号 dict 重建 SignalFunnelInput，提取维度信息。"""
        from app.services.signal_quality_funnel import SignalFunnelInput

        factor_scores = signal.get("factor_scores") or {}
        if not isinstance(factor_scores, dict):
            factor_scores = {}
        extra_meta = signal.get("extra_metadata") or {}
        if not isinstance(extra_meta, dict):
            extra_meta = {}
        dimensions = signal.get("dimensions")
        if not isinstance(dimensions, list):
            dimensions = (
                extra_meta.get("dimensions") or factor_scores.get("dimensions") or []
            )

        def _from(*keys, default=None):
            for k in keys:
                for src in (signal, extra_meta, factor_scores):
                    if isinstance(src, dict) and src.get(k) is not None:
                        return src[k]
            return default

        def _dim_dir(name: str) -> int:
            for item in dimensions:
                if isinstance(item, dict) and item.get("name") == name:
                    try:
                        return int(item.get("direction", 0))
                    except Exception:
                        return 0
            return 0

        confidence = float(
            signal.get("confidence") or signal.get("fused_confidence") or 0.0
        )
        if confidence > 1.0:
            confidence = confidence / 100.0

        return SignalFunnelInput(
            signal_id=signal.get("id"),
            signal_type=str(signal.get("signal_type") or "ENTRY").upper(),
            signal_strength=float(signal.get("signal_strength") or 0.0),
            symbol=str(signal.get("symbol") or ""),
            direction=str(signal.get("direction") or "LONG").upper(),
            regime=regime or "SIDEWAYS",
            composite_score=confidence,
            aligned_count=int(_from("aligned_count", default=0) or 0),
            aligned_dims=list(_from("aligned_dims", default=[]) or []),
            opposing_dims=list(_from("opposing_dims", default=[]) or []),
            neutral_dims=list(_from("neutral_dims", default=[]) or []),
            tech_direction=_dim_dir("technical"),
            fundamental_direction=_dim_dir("fundamental"),
            historical_ic=_from("historical_ic"),
            timing_quality=_from("timing_quality"),
        )

    async def _create_exit_signals(
        self,
        *,
        account_id: str,
        symbols_to_close: List[str],
        position_candidates: List[CapacityCandidate],
        cycle_id: str,
        db: AsyncSession,
    ) -> List[str]:
        """为被竞争淘汰的持仓创建 EXIT 信号。"""
        from datetime import datetime as _dt
        from uuid import uuid4 as _uuid4

        from app.models.trading_signal import (SignalSource, SignalStatus,
                                               SignalType, TradingSignal)

        pos_map = {c.symbol: c for c in position_candidates}
        created_symbols: List[str] = []

        for symbol in symbols_to_close:
            try:
                candidate = pos_map.get(symbol)
                raw_score = candidate.raw_score if candidate else 50.0
                note = (
                    f"席位竞争淘汰：该持仓在与新信号的统一质量排序中排名末尾，"
                    f"被新信号替换（admission_score={candidate.admission_score:.1f}，"
                    f"cycle_id={cycle_id}）"
                    if candidate
                    else f"席位竞争淘汰（cycle_id={cycle_id}）"
                )
                signal = TradingSignal(
                    signal_id=str(_uuid4()),
                    account_id=account_id,
                    user_id=account_id,
                    symbol=symbol,
                    signal_type=SignalType.EXIT,
                    signal_source=SignalSource.RISK_MGMT,
                    status=SignalStatus.GENERATED,
                    direction="LONG",  # EXIT 方向在执行时按持仓方向覆盖
                    quantity_mode="PCT_EQUITY",
                    quantity_value=1.0,  # 100% 平仓
                    suggested_quantity=None,
                    signal_strength=max(0.1, (100 - raw_score) / 100),
                    confidence=max(0.1, (100 - raw_score) / 100),
                    risk_score=(100 - raw_score) / 100,
                    priority=95,
                    notes=note,
                    created_at=_dt.utcnow(),
                    extra_metadata={
                        "closing_intent": "EXIT",
                        "execution_path": "FAST_CLOSE",
                        "generated_by": "CapacityArbiter",
                        "seat_competition": True,
                        "seat_competition_cycle": cycle_id,
                        "capacity_arbiter_score": raw_score,
                    },
                )
                db.add(signal)
                created_symbols.append(symbol)
                logger.info(
                    "[CapacityArbiter] Created EXIT signal for %s (score=%.1f)",
                    symbol,
                    raw_score,
                )
            except Exception as e:
                logger.error(
                    "[CapacityArbiter] Failed to create EXIT signal for %s: %s",
                    symbol,
                    e,
                )

        if created_symbols:
            try:
                await db.flush()
            except Exception as e:
                logger.error(
                    "[CapacityArbiter] DB flush failed after EXIT signals: %s", e
                )

        return created_symbols

    async def _write_capacity_log(
        self,
        *,
        account_id: str,
        regime: str,
        decision: ArbiterDecision,
        db: AsyncSession,
    ) -> None:
        """写容量决策审计日志。"""
        try:
            from app.models.capacity_decision_log import (ArbiterTriggerReason,
                                                          CapacityDecisionLog)

            pos_candidates = [
                c
                for c in decision.candidates_snapshot
                if c.get("type") == CANDIDATE_POSITION
            ]
            eliminated_positions_detail = [
                {"symbol": sym} for sym in decision.positions_to_close
            ]
            eliminated_signals_detail = [
                {
                    "signal_id": sig.get("id"),
                    "symbol": sig.get("symbol"),
                }
                for sig in decision.rejected_signals
            ]
            approved_signals_detail = [
                {
                    "signal_id": sig.get("id"),
                    "symbol": sig.get("symbol"),
                }
                for sig in decision.approved_signals
            ]

            log = CapacityDecisionLog(
                account_id=account_id,
                cycle_id=decision.cycle_id,
                regime=regime,
                trigger_reason=ArbiterTriggerReason.CAPACITY_OVERFLOW.value,
                max_positions=decision.max_positions,
                positions_count=decision.positions_count,
                signals_count=decision.signals_count,
                overflow_count=decision.overflow,
                candidates_snapshot=decision.candidates_snapshot,
                eliminated_positions=eliminated_positions_detail,
                eliminated_signals=eliminated_signals_detail,
                approved_signals=approved_signals_detail,
                min_edge_protected=decision.min_edge_protected,
                cooldown_protected=decision.cooldown_protected,
                min_hold_protected=decision.min_hold_protected,
                max_replacements_cap=decision.max_replacements_cap,
                dry_run=decision.dry_run,
                replacement_triggered=decision.replacement_triggered,
            )
            db.add(log)
            await db.flush()
        except Exception as e:
            logger.warning(
                "[CapacityArbiter] Failed to write capacity decision log (non-fatal): %s",
                e,
            )


# ── 全局单例 ─────────────────────────────────────────────────────────────────
capacity_arbiter_service = CapacityArbiterService()
