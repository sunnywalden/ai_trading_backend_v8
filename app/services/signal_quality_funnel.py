"""V11.0.1: SignalQualityFunnel — 五层信号质量漏斗 + M1.5 阈值软化

五层过滤体系，实现"窄入高出"的信号精英化：
  Layer 0: 宇宙过滤     — 流动性/市值筛选
  Layer 1: 体制门控     — 市场体制 × 信号方向准入规则
  Layer 2: 组合预检     — 持仓数上限 / 日配额 / 相关性限制
  Layer 3: 共振验证     — 多维共振 + 反共振一票否决
  Layer 4: 置信度校准门 — Conviction Score ≥ 阈值（V11: 支持摩擦感知软化）

每个信号无论通过还是被拒，均写入 SignalQualityAuditLog 审计日志。
被 Layer 3/4 拒绝的信号，在 ghost_trade_enabled 时创建 GhostTrade 虚拟跟踪。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.signal_quality_audit_log import FunnelResult, RejectionReason
from app.services.signal_conviction_scorer import (
    ConvictionComponents,
    signal_conviction_scorer,
)
from app.services.signal_quality_config import (
    SignalQualityConfig,
    get_regime_adjusted_config,
    get_signal_quality_config,
)

logger = logging.getLogger(__name__)


class SignalQualityTier:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    ELITE = "ELITE"


@dataclass
class SignalFunnelInput:
    """输入漏斗的信号元数据"""

    symbol: str
    direction: str  # "LONG" / "SHORT"
    regime: str  # 当前市场体制
    signal_id: Optional[int] = None
    signal_type: str = "ENTRY"  # ENTRY / ADD / REDUCE / EXIT / STOP_LOSS_EXIT
    signal_strength: float = 0.0  # 0-100，原始信号强度

    # ── 六维评分（来自 SignalFusionEngine）──
    composite_score: float = 0.5  # 0-1
    aligned_count: int = 0
    aligned_dims: list[str] = field(default_factory=list)
    opposing_dims: list[str] = field(default_factory=list)
    neutral_dims: list[str] = field(default_factory=list)
    tech_direction: int = 0  # +1/-1/0
    fundamental_direction: int = 0  # +1/-1/0
    macro_score: float = 0.5  # 0-1（单维度原始分）
    options_score: float = 0.5  # 0-1

    # ── 流动性数据（Layer 0）──
    adv_usd: Optional[float] = None  # 日均成交量（美元）
    market_cap: Optional[float] = None  # 市值（美元）

    # ── 相关性数据（Layer 2）──
    max_correlation_with_existing: Optional[float] = None

    # ── 可选增强数据（Layer 4）──
    historical_ic: Optional[float] = None  # 历史 IC（0-1）
    timing_quality: Optional[float] = None  # 时机质量（0-1）

    # ── 时间戳 ──
    generated_at: Optional[str] = None  # ISO 格式时间字符串


@dataclass
class FunnelDecision:
    """漏斗评估结果"""

    passed: bool
    symbol: str
    signal_id: Optional[int]

    # 拒绝信息
    rejected_at_layer: Optional[int] = None
    rejection_reason: Optional[str] = None
    rejection_detail: Optional[str] = None

    # Conviction Score 详情（仅 Layer 3+ 评估后有值）
    conviction: Optional[ConvictionComponents] = None
    signal_quality_tier: str = SignalQualityTier.LOW
    signal_quality_score: float = 0.0
    quota_exempt: bool = False

    # 上下文快照
    concurrent_positions: int = 0
    daily_signals_used: int = 0
    regime: str = ""


@dataclass
class SignalQualityProfile:
    """供排队与日配额豁免使用的信号质量画像。"""

    tier: str
    score: float
    quota_exempt: bool
    conviction: ConvictionComponents


class SignalQualityFunnel:
    """
    五层信号质量漏斗。

    使用示例::

        funnel = SignalQualityFunnel()
        decision = await funnel.evaluate(signal_input, db)
        if decision.passed:
            # 推进至 AutonomousEngine 执行
        else:
            # 记录拒绝原因，可选创建 GhostTrade
    """

    async def evaluate(
        self,
        signal: SignalFunnelInput,
        db: AsyncSession,
        current_positions_count: int = 0,
        daily_signals_executed: int = 0,
        arbiter_approved: bool = False,
    ) -> FunnelDecision:
        """
        对单个信号执行五层漏斗评估。

        Args:
            signal:                  信号输入对象
            db:                      DB session（用于写审计日志）
            current_positions_count: 当前实时持仓数量
            daily_signals_executed:  今日已推进信号数
            arbiter_approved:        V10.5.2 — 该信号已通过 CapacityArbiter 席位竞争，
                                     Layer 2 容量拒绝应软过（skip hard-reject）。

        Returns:
            FunnelDecision（passed=True 则可执行，False 含拒绝原因）
        """
        cfg = get_signal_quality_config()
        regime_cfg = get_regime_adjusted_config(signal.regime)

        decision = FunnelDecision(
            passed=False,
            symbol=signal.symbol,
            signal_id=signal.signal_id,
            regime=signal.regime,
            concurrent_positions=current_positions_count,
            daily_signals_used=daily_signals_executed,
        )
        is_closing = str(signal.signal_type or "ENTRY").upper() in {
            "REDUCE",
            "EXIT",
            "STOP_LOSS_EXIT",
            "TAKE_PROFIT_EXIT",
            "FORCE_EXIT",
        }
        quality_profile = self.preview_quality(signal, cfg=cfg, regime_cfg=regime_cfg)
        decision.conviction = quality_profile.conviction
        decision.signal_quality_tier = quality_profile.tier
        decision.signal_quality_score = quality_profile.score
        decision.quota_exempt = quality_profile.quota_exempt

        # ── Layer 0: 宇宙过滤 ───────────────────────────────────────────────
        reject = self._layer0_universe(signal, cfg)
        if reject:
            decision.rejected_at_layer = 0
            decision.rejection_reason = reject[0]
            decision.rejection_detail = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 1: 体制门控 ────────────────────────────────────────────────
        reject = self._layer1_regime(signal, regime_cfg)
        if reject:
            decision.rejected_at_layer = 1
            decision.rejection_reason = reject[0]
            decision.rejection_detail = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 2: 组合预检 ────────────────────────────────────────────────
        reject = self._layer2_portfolio(
            signal,
            regime_cfg,
            current_positions_count,
            daily_signals_executed,
            is_closing=is_closing,
            quality_profile=quality_profile,
            arbiter_approved=arbiter_approved,
        )
        if reject:
            decision.rejected_at_layer = 2
            decision.rejection_reason = reject[0]
            decision.rejection_detail = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 3: 多维共振验证 ────────────────────────────────────────────
        reject = self._layer3_resonance(signal, regime_cfg)
        if reject:
            decision.rejected_at_layer = 3
            decision.rejection_reason = reject[0]
            decision.rejection_detail = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            await self._create_ghost_trade(decision, signal, cfg, db)
            return decision

        # ── Layer 4: 置信度校准门 ─────────────────────────────────────────────
        conviction = quality_profile.conviction
        decision.conviction = conviction

        # V11.0.1 M2.3: REDUCE/EXIT（is_closing）快速通道
        # 来自 RISK_MGMT 的平仓信号不应被置信度阈值阻断；
        # 也适用于 false_hold_protection=True 标记的信号
        fast_path_bypass = is_closing and (
            str(signal.signal_type or "").upper()
            in {"REDUCE", "EXIT", "STOP_LOSS_EXIT", "FORCE_EXIT"}
        )
        if fast_path_bypass:
            decision.passed = True
            decision.rejection_detail = "Layer4 bypassed (is_closing fast-path)"
            await self._write_audit(decision, signal, cfg, db)
            logger.debug(
                "[SignalFunnel] Layer4 fast-path bypass %s %s type=%s",
                signal.symbol,
                signal.direction,
                signal.signal_type,
            )
            return decision

        threshold = regime_cfg.get(
            "SIGNAL_CONFIDENCE_THRESHOLD", cfg.SIGNAL_CONFIDENCE_THRESHOLD
        )

        # V11.0.1 M1.5.2: 阈值摩擦感知软化
        # 条件：主开关开启 + 非平仓信号 + 满足 composite/resonance 门控
        effective_threshold = threshold
        soft_threshold_applied = False
        if not is_closing and getattr(
            settings, "CAPITAL_VELOCITY_V1101_ENABLED", False
        ):
            effective_threshold, soft_threshold_applied = (
                await self._compute_soft_threshold(
                    signal=signal,
                    conviction=conviction,
                    base_threshold=threshold,
                    regime=signal.regime,
                    cfg=cfg,
                )
            )

        reject = self._layer4_conviction(conviction, cfg, effective_threshold)
        if reject:
            # V11: 记录摩擦状态（仅 LOW_CONVICTION 触发，其他拒绝原因不计入摩擦）
            if (
                not is_closing
                and getattr(settings, "CAPITAL_VELOCITY_V1101_ENABLED", False)
                and reject[0] == RejectionReason.LOW_CONVICTION
            ):
                from app.services.conviction_friction_tracker import (
                    conviction_friction_tracker,
                )

                await conviction_friction_tracker.record_rejection(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    regime=signal.regime,
                    conviction=conviction.conviction_score,
                    threshold=threshold,
                    composite_score=signal.composite_score * 100,
                    resonance_bonus=conviction.resonance_bonus,
                )
            decision.rejected_at_layer = 4
            decision.rejection_reason = reject[0]
            decision.rejection_detail = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            await self._create_ghost_trade(decision, signal, cfg, db)
            return decision

        # 通过 Layer 4：重置摩擦计数
        if not is_closing and getattr(
            settings, "CAPITAL_VELOCITY_V1101_ENABLED", False
        ):
            from app.services.conviction_friction_tracker import (
                conviction_friction_tracker,
            )

            await conviction_friction_tracker.record_pass(
                symbol=signal.symbol,
                direction=signal.direction,
                regime=signal.regime,
            )
            if soft_threshold_applied:
                logger.info(
                    "[SignalFunnel] ✅ Layer4 SOFT_THRESHOLD_APPLIED %s %s "
                    "conviction=%.1f effective_threshold=%d (base=%d)",
                    signal.symbol,
                    signal.direction,
                    conviction.conviction_score,
                    effective_threshold,
                    threshold,
                )

        # ── 通过所有层 ──────────────────────────────────────────────────────
        decision.passed = True
        await self._write_audit(decision, signal, cfg, db)
        logger.info(
            f"[SignalFunnel] ✅ PASSED {signal.symbol} {signal.direction}@{signal.regime} "
            f"conviction={conviction.conviction_score:.1f} quality={quality_profile.tier}"
        )
        return decision

    def preview_quality(
        self,
        signal: SignalFunnelInput,
        *,
        cfg: Optional[SignalQualityConfig] = None,
        regime_cfg: Optional[dict] = None,
    ) -> SignalQualityProfile:
        """在真正进入漏斗前预估信号质量，用于队列排序和日配额豁免。"""
        cfg = cfg or get_signal_quality_config()
        regime_cfg = regime_cfg or get_regime_adjusted_config(signal.regime)
        conviction = self._compute_conviction(signal)
        tier = self._classify_quality_tier(signal, conviction, cfg)
        score = round(conviction.conviction_score, 2)
        quota_exempt = tier == SignalQualityTier.ELITE
        logger.debug(
            "[SignalFunnel] preview quality %s %s -> %s score=%.1f quota_exempt=%s",
            signal.symbol,
            signal.direction,
            tier,
            score,
            quota_exempt,
        )
        return SignalQualityProfile(
            tier=tier,
            score=score,
            quota_exempt=quota_exempt,
            conviction=conviction,
        )

    def _compute_conviction(self, signal: SignalFunnelInput) -> ConvictionComponents:
        return signal_conviction_scorer.compute(
            symbol=signal.symbol,
            signal_direction=signal.direction,
            regime=signal.regime,
            composite_score=self._normalize_ratio(signal.composite_score, default=0.5),
            aligned_count=signal.aligned_count,
            aligned_dims=signal.aligned_dims,
            opposing_dims=signal.opposing_dims,
            neutral_dims=signal.neutral_dims,
            tech_direction=signal.tech_direction,
            fundamental_direction=signal.fundamental_direction,
            macro_score=self._normalize_ratio(signal.macro_score, default=0.5),
            options_score=self._normalize_ratio(signal.options_score, default=0.5),
            historical_ic=self._normalize_optional_ratio(signal.historical_ic),
            timing_quality=self._normalize_optional_ratio(signal.timing_quality),
        )

    @staticmethod
    def _normalize_ratio(value: Optional[float], *, default: float = 0.0) -> float:
        if value is None:
            return default
        val = float(value)
        if val > 1.0:
            val = val / 100.0
        return max(0.0, min(1.0, val))

    @classmethod
    def _normalize_optional_ratio(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return cls._normalize_ratio(value)

    def _classify_quality_tier(
        self,
        signal: SignalFunnelInput,
        conviction: ConvictionComponents,
        cfg: SignalQualityConfig,
    ) -> str:
        if conviction.anti_resonance_killed:
            return SignalQualityTier.LOW

        if (
            conviction.conviction_score >= cfg.ELITE_SIGNAL_SCORE
            and conviction.calibrated_lower_bound >= cfg.ELITE_SIGNAL_FLOOR
            and signal.aligned_count >= cfg.ELITE_MIN_ALIGNED_DIMS
        ):
            return SignalQualityTier.ELITE
        if conviction.conviction_score >= cfg.HIGH_QUALITY_SIGNAL_SCORE:
            return SignalQualityTier.HIGH
        if conviction.conviction_score >= cfg.MEDIUM_QUALITY_SIGNAL_SCORE:
            return SignalQualityTier.MEDIUM
        return SignalQualityTier.LOW

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 0: 宇宙过滤
    # ──────────────────────────────────────────────────────────────────────────
    def _layer0_universe(
        self,
        signal: SignalFunnelInput,
        cfg: SignalQualityConfig,
    ) -> Optional[tuple[str, str]]:
        """返回 (rejection_reason, detail) 或 None（通过）"""
        if signal.adv_usd is not None and signal.adv_usd < cfg.MIN_ADV_THRESHOLD:
            return (
                RejectionReason.LOW_LIQUIDITY,
                f"ADV ${signal.adv_usd:,.0f} < 最低要求 ${cfg.MIN_ADV_THRESHOLD:,.0f}",
            )
        if signal.market_cap is not None and signal.market_cap < cfg.MIN_MARKET_CAP:
            return (
                RejectionReason.LOW_LIQUIDITY,
                f"市值 ${signal.market_cap/1e9:.2f}B < 最低要求 ${cfg.MIN_MARKET_CAP/1e9:.2f}B",
            )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 1: 体制门控
    # ──────────────────────────────────────────────────────────────────────────
    def _layer1_regime(
        self,
        signal: SignalFunnelInput,
        regime_cfg: dict,
    ) -> Optional[tuple[str, str]]:
        long_allowed = regime_cfg.get("long_allowed", True)
        short_allowed = regime_cfg.get("short_allowed", True)

        if signal.direction == "LONG" and not long_allowed:
            return (
                RejectionReason.REGIME_DIRECTION,
                f"{signal.regime} 体制不允许做多信号（long_allowed=False）",
            )
        if signal.direction == "SHORT" and not short_allowed:
            return (
                RejectionReason.REGIME_DIRECTION,
                f"{signal.regime} 体制不允许做空信号（short_allowed=False）",
            )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 2: 组合预检
    # ──────────────────────────────────────────────────────────────────────────
    def _layer2_portfolio(
        self,
        signal: SignalFunnelInput,
        regime_cfg: dict,
        current_positions: int,
        daily_executed: int,
        is_closing: bool = False,
        quality_profile: Optional[SignalQualityProfile] = None,
        arbiter_approved: bool = False,
    ) -> Optional[tuple[str, str]]:
        max_pos = regime_cfg.get("MAX_CONCURRENT_POSITIONS", 6)
        max_daily = regime_cfg.get("MAX_DAILY_SIGNALS", 5)
        max_corr = regime_cfg.get("MAX_POSITION_CORRELATION", 0.70)

        if is_closing:
            return None

        if current_positions >= max_pos:
            # V10.5.2: 若席位竞争仲裁已通过该信号，则跳过硬拒绝，允许继续评估后续层级。
            # 若仲裁功能关闭或该信号未被仲裁覆盖，维持原有硬拒逻辑。
            from app.services.signal_quality_config import (
                get_signal_quality_config as _get_cfg,
            )

            _cfg = _get_cfg()
            if _cfg.CAPACITY_REPLACEMENT_ENABLED and arbiter_approved:
                logger.debug(
                    "[SignalFunnel] Layer2 capacity soft-pass: %s approved by CapacityArbiter "
                    "(positions=%d, max=%d)",
                    signal.symbol,
                    current_positions,
                    max_pos,
                )
                # 不返回拒绝，继续后续 Layer 评估
            else:
                return (
                    RejectionReason.MAX_POSITIONS_REACHED,
                    f"当前持仓数 {current_positions} 已达上限 {max_pos}",
                )
        if daily_executed >= max_daily:
            if quality_profile and quality_profile.quota_exempt:
                logger.info(
                    "[SignalFunnel] ELITE signal bypassing daily quota: %s score=%.1f used=%s/%s",
                    signal.symbol,
                    quality_profile.score,
                    daily_executed,
                    max_daily,
                )
            else:
                return (
                    RejectionReason.DAILY_QUOTA_EXHAUSTED,
                    f"今日已推进信号 {daily_executed} 个，已达日配额 {max_daily}",
                )
        if (
            signal.max_correlation_with_existing is not None
            and signal.max_correlation_with_existing >= max_corr
        ):
            return (
                RejectionReason.HIGH_CORRELATION,
                f"与现有持仓最大相关系数 {signal.max_correlation_with_existing:.2f} ≥ {max_corr:.2f}",
            )
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 3: 多维共振验证
    # ──────────────────────────────────────────────────────────────────────────
    def _layer3_resonance(
        self,
        signal: SignalFunnelInput,
        regime_cfg: dict,
    ) -> Optional[tuple[str, str]]:
        metadata_reject = self._layer3_missing_resonance_metadata(signal)
        if metadata_reject:
            return metadata_reject

        min_dims = regime_cfg.get("SIGNAL_RESONANCE_MIN_DIMS", 4)
        require_tech = regime_cfg.get("RESONANCE_REQUIRED_TECHNICAL", True)

        # 反共振  技术/基本面方向对立
        if (
            signal.tech_direction != 0
            and signal.fundamental_direction != 0
            and signal.tech_direction != signal.fundamental_direction
        ):
            return (
                RejectionReason.ANTI_RESONANCE_KILL,
                f"技术面(direction={signal.tech_direction})与基本面(direction={signal.fundamental_direction})方向对立",
            )

        # CRISIS 做多一票否决
        if signal.regime == "CRISIS" and signal.direction == "LONG":
            return (
                RejectionReason.REGIME_BLOCKED,
                "CRISIS 体制禁止做多，一票否决",
            )

        # 同向维度数量不足
        if signal.aligned_count < min_dims:
            return (
                RejectionReason.INSUFFICIENT_RESONANCE,
                (
                    f"同向维度数 {signal.aligned_count} < 最低要求 {min_dims}；"
                    f"对齐={signal.aligned_dims}，反向={signal.opposing_dims}"
                ),
            )

        # 强制要求 technical 在同向列表中
        if require_tech and "technical" not in signal.aligned_dims:
            return (
                RejectionReason.INSUFFICIENT_RESONANCE,
                f"技术面(technical)未在同向维度中（aligned={signal.aligned_dims}），"
                f"强制要求 RESONANCE_REQUIRED_TECHNICAL=True",
            )

        return None

    def _layer3_missing_resonance_metadata(
        self,
        signal: SignalFunnelInput,
    ) -> Optional[tuple[str, str]]:
        list_total = (
            len(signal.aligned_dims)
            + len(signal.opposing_dims)
            + len(signal.neutral_dims)
        )
        has_directionality = (
            signal.tech_direction != 0 or signal.fundamental_direction != 0
        )

        if signal.aligned_count > 0 and not signal.aligned_dims:
            return (
                RejectionReason.MISSING_RESONANCE_METADATA,
                (
                    "aligned_count 已存在，但 aligned_dims 为空；"
                    "信号共振元数据不完整，无法可靠评估 Layer 3"
                ),
            )

        if signal.aligned_count <= 0 and list_total > 0:
            return (
                RejectionReason.MISSING_RESONANCE_METADATA,
                (
                    "aligned_dims/opposing_dims/neutral_dims 已存在，但 aligned_count 缺失或为 0；"
                    "信号共振元数据不一致，无法可靠评估 Layer 3"
                ),
            )

        if signal.aligned_count <= 0 and list_total == 0 and not has_directionality:
            return (
                RejectionReason.MISSING_RESONANCE_METADATA,
                (
                    "aligned_count、共振维度列表以及 technical/fundamental 方向均缺失；"
                    "信号缺少共振元数据，无法区分真实共振不足与上游数据缺失"
                ),
            )

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # V11.0.1 M1.5: 置信度阈值摩擦感知软化
    # ──────────────────────────────────────────────────────────────────────────
    async def _compute_soft_threshold(
        self,
        *,
        signal: "SignalFunnelInput",
        conviction: "ConvictionComponents",
        base_threshold: int,
        regime: str,
        cfg: "SignalQualityConfig",
    ) -> tuple[int, bool]:
        """
        计算摩擦感知软化后的有效阈值。

        Returns:
            (effective_threshold, soft_threshold_applied)
            - effective_threshold: 实际使用的置信度阈值（可能低于 base_threshold）
            - soft_threshold_applied: 是否触发了软化
        """
        try:
            from app.services.conviction_friction_tracker import (
                conviction_friction_tracker,
            )

            min_rounds = getattr(settings, "CONVICTION_FRICTION_MIN_ROUNDS", 3)
            composite_floor = int(getattr(cfg, "CONVICTION_SOFT_COMPOSITE_FLOOR", 96))
            resonance_floor = int(getattr(cfg, "CONVICTION_SOFT_RESONANCE_FLOOR", 80))
            max_per_cycle = getattr(settings, "CONVICTION_SOFT_RELIEF_MAX_PER_CYCLE", 1)
            soft_floor_bull = getattr(settings, "CONVICTION_SOFT_FLOOR_BULL", 88)
            soft_floor_default = getattr(settings, "CONVICTION_SOFT_FLOOR_DEFAULT", 90)
            relief_max = getattr(settings, "CONVICTION_SOFT_RELIEF_MAX", 3)

            friction_delta = getattr(settings, "CONVICTION_FRICTION_DELTA", 3)
            near_miss_floor = base_threshold - friction_delta
            conv_score = conviction.conviction_score

            # 仅当 conviction 在近命中区间内时，才查询摩擦状态
            if conv_score < near_miss_floor:
                return base_threshold, False

            state = await conviction_friction_tracker.get_friction_state(
                signal.symbol, signal.direction, regime
            )
            if state is None or state.rejection_count < min_rounds:
                return base_threshold, False

            # 独立维度门控（直接用原始分值）
            composite_ok = (signal.composite_score * 100) >= composite_floor
            resonance_ok = conviction.resonance_bonus >= resonance_floor
            if not (composite_ok and resonance_ok):
                logger.debug(
                    "[SoftThreshold] %s %s gate fail composite=%.1f/%d "
                    "resonance=%.1f/%d",
                    signal.symbol,
                    signal.direction,
                    signal.composite_score * 100,
                    composite_floor,
                    conviction.resonance_bonus,
                    resonance_floor,
                )
                return base_threshold, False

            # 周期配额检查
            can_use = await conviction_friction_tracker.can_use_soft_relief(
                symbol=signal.symbol,
                direction=signal.direction,
                regime=regime,
                max_per_cycle=max_per_cycle,
            )
            if not can_use:
                logger.debug(
                    "[SoftThreshold] %s %s quota exhausted in cycle",
                    signal.symbol,
                    signal.direction,
                )
                return base_threshold, False

            # 计算软化幅度
            gap = base_threshold - conv_score
            relief = min(gap, relief_max)
            absolute_floor = (
                soft_floor_bull
                if regime.upper() == "BULL_TREND"
                else soft_floor_default
            )
            effective = max(int(base_threshold - relief), absolute_floor)
            if effective >= base_threshold:
                return base_threshold, False

            # 记录软化配额使用
            await conviction_friction_tracker.record_soft_relief_used(
                symbol=signal.symbol,
                direction=signal.direction,
                regime=regime,
            )
            logger.info(
                "[SoftThreshold] applied %s %s regime=%s "
                "threshold=%d→%d conviction=%.1f rounds=%d",
                signal.symbol,
                signal.direction,
                regime,
                base_threshold,
                effective,
                conv_score,
                state.rejection_count,
            )
            return effective, True
        except Exception as exc:
            logger.warning("[SoftThreshold] computation failed: %s", exc)
            return base_threshold, False

    # ──────────────────────────────────────────────────────────────────────────
    # Layer 4: 置信度校准门
    # ──────────────────────────────────────────────────────────────────────────
    def _layer4_conviction(
        self,
        conviction: ConvictionComponents,
        cfg: SignalQualityConfig,
        threshold: int,
    ) -> Optional[tuple[str, str]]:
        # 反共振 Kill Switch 已处理
        if conviction.anti_resonance_killed:
            return (
                RejectionReason.ANTI_RESONANCE_KILL,
                conviction.kill_reason,
            )

        if conviction.conviction_score < threshold:
            return (
                RejectionReason.LOW_CONVICTION,
                (
                    f"Conviction Score {conviction.conviction_score:.1f} < "
                    f"阈值 {threshold}（"
                    f"composite={conviction.composite_score:.1f}, "
                    f"resonance_bonus={conviction.resonance_bonus:.0f}, "
                    f"regime_alignment={conviction.regime_alignment:.0f}）"
                ),
            )

        if conviction.calibrated_lower_bound < cfg.SIGNAL_CONFIDENCE_FLOOR:
            return (
                RejectionReason.LOW_CALIBRATED_FLOOR,
                (
                    f"校准下界 {conviction.calibrated_lower_bound:.1f} < "
                    f"最低要求 {cfg.SIGNAL_CONFIDENCE_FLOOR}（conviction={conviction.conviction_score:.1f}）"
                ),
            )

        if cfg.MIN_EXPECTED_SHARPE > 0:
            # 简化估算：composite_score > 0.7 * (regime_alignment/100) 视为夏普满足
            estimated_sharpe = (
                (conviction.composite_score / 100)
                * (conviction.regime_alignment / 100)
                * 2.0  # 粗粒度系数
            )
            if estimated_sharpe < cfg.MIN_EXPECTED_SHARPE:
                return (
                    RejectionReason.LOW_EXPECTED_SHARPE,
                    (
                        f"预期夏普估算 {estimated_sharpe:.2f} < "
                        f"最低要求 {cfg.MIN_EXPECTED_SHARPE}"
                    ),
                )

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # 写入审计日志
    # ──────────────────────────────────────────────────────────────────────────
    async def _write_audit(
        self,
        decision: FunnelDecision,
        signal: SignalFunnelInput,
        cfg: SignalQualityConfig,
        db: AsyncSession,
    ) -> None:
        """将漏斗评估结果写入 SignalQualityAuditLog。"""
        try:
            from app.services.signal_audit_log_service import signal_audit_log_service

            await signal_audit_log_service.create(
                db=db,
                symbol=signal.symbol,
                signal_id=signal.signal_id,
                funnel_result=(
                    FunnelResult.PASSED if decision.passed else FunnelResult.REJECTED
                ),
                rejected_at_layer=decision.rejected_at_layer,
                rejection_reason=decision.rejection_reason,
                rejection_detail=decision.rejection_detail,
                conviction=decision.conviction,
                composite_score=signal.composite_score * 100,
                aligned_count=signal.aligned_count,
                aligned_dims=signal.aligned_dims,
                opposing_dims=signal.opposing_dims,
                neutral_dims=signal.neutral_dims,
                anti_resonance_triggered=(
                    decision.conviction.anti_resonance_killed
                    if decision.conviction
                    else False
                ),
                signal_direction=signal.direction,
                regime=signal.regime,
                concurrent_positions=decision.concurrent_positions,
                daily_signals_used=decision.daily_signals_used,
                generated_at=signal.generated_at,
            )
        except Exception as e:
            logger.warning(f"[SignalFunnel] 审计日志写入失败（不影响主流程）: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # 创建幽灵交易（被 Layer 3/4 拒绝时）
    # ──────────────────────────────────────────────────────────────────────────
    async def _create_ghost_trade(
        self,
        decision: FunnelDecision,
        signal: SignalFunnelInput,
        cfg: SignalQualityConfig,
        db: AsyncSession,
    ) -> None:
        """为被拒绝的信号创建幽灵交易虚拟跟踪。"""
        if not cfg.GHOST_TRADE_ENABLED:
            return
        if decision.rejection_reason == RejectionReason.MISSING_RESONANCE_METADATA:
            logger.info(
                "[SignalFunnel] Skip ghost trade for %s because rejection is data-quality related",
                signal.symbol,
            )
            return
        try:
            from app.services.ghost_trade_service import ghost_trade_service

            await ghost_trade_service.create_from_rejected_signal(
                db=db,
                symbol=signal.symbol,
                signal_id=signal.signal_id,
                direction=signal.direction,
                rejection_reason=decision.rejection_reason,
                rejected_at_layer=decision.rejected_at_layer,
                conviction_at_rejection=(
                    decision.conviction.conviction_score
                    if decision.conviction
                    else None
                ),
                max_tracking_days=cfg.GHOST_TRADE_MAX_DAYS,
            )
        except Exception as e:
            logger.warning(f"[SignalFunnel] 幽灵交易创建失败（不影响主流程）: {e}")


# ── 模块级单例 ────────────────────────────────────────────────────────────────
signal_quality_funnel = SignalQualityFunnel()
