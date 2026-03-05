"""V10.4.2: SignalQualityFunnel — 五层信号质量漏斗

五层过滤体系，实现"窄入高出"的信号精英化：
  Layer 0: 宇宙过滤     — 流动性/市值筛选
  Layer 1: 体制门控     — 市场体制 × 信号方向准入规则
  Layer 2: 组合预检     — 持仓数上限 / 日配额 / 相关性限制
  Layer 3: 共振验证     — 多维共振 + 反共振一票否决
  Layer 4: 置信度校准门 — Conviction Score ≥ 阈值

每个信号无论通过还是被拒，均写入 SignalQualityAuditLog 审计日志。
被 Layer 3/4 拒绝的信号，在 ghost_trade_enabled 时创建 GhostTrade 虚拟跟踪。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.signal_quality_config import (
    get_signal_quality_config,
    get_regime_adjusted_config,
    SignalQualityConfig,
)
from app.services.signal_conviction_scorer import (
    signal_conviction_scorer,
    ConvictionComponents,
)
from app.models.signal_quality_audit_log import RejectionReason, FunnelResult

logger = logging.getLogger(__name__)


@dataclass
class SignalFunnelInput:
    """输入漏斗的信号元数据"""
    symbol:    str
    direction: str                   # "LONG" / "SHORT"
    regime:    str                   # 当前市场体制
    signal_id: Optional[int] = None

    # ── 六维评分（来自 SignalFusionEngine）──
    composite_score:       float = 0.5     # 0-1
    aligned_count:         int   = 0
    aligned_dims:          list[str] = field(default_factory=list)
    opposing_dims:         list[str] = field(default_factory=list)
    neutral_dims:          list[str] = field(default_factory=list)
    tech_direction:        int   = 0       # +1/-1/0
    fundamental_direction: int   = 0       # +1/-1/0
    macro_score:           float = 0.5     # 0-1（单维度原始分）
    options_score:         float = 0.5     # 0-1

    # ── 流动性数据（Layer 0）──
    adv_usd:    Optional[float] = None    # 日均成交量（美元）
    market_cap: Optional[float] = None   # 市值（美元）

    # ── 相关性数据（Layer 2）──
    max_correlation_with_existing: Optional[float] = None

    # ── 可选增强数据（Layer 4）──
    historical_ic:   Optional[float] = None  # 历史 IC（0-1）
    timing_quality:  Optional[float] = None  # 时机质量（0-1）

    # ── 时间戳 ──
    generated_at: Optional[str] = None      # ISO 格式时间字符串


@dataclass
class FunnelDecision:
    """漏斗评估结果"""
    passed: bool
    symbol: str
    signal_id: Optional[int]

    # 拒绝信息
    rejected_at_layer: Optional[int] = None
    rejection_reason:  Optional[str] = None
    rejection_detail:  Optional[str] = None

    # Conviction Score 详情（仅 Layer 3+ 评估后有值）
    conviction: Optional[ConvictionComponents] = None

    # 上下文快照
    concurrent_positions: int = 0
    daily_signals_used:   int = 0
    regime:               str = ""


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
    ) -> FunnelDecision:
        """
        对单个信号执行五层漏斗评估。

        Args:
            signal:                  信号输入对象
            db:                      DB session（用于写审计日志）
            current_positions_count: 当前实时持仓数量
            daily_signals_executed:  今日已推进信号数

        Returns:
            FunnelDecision（passed=True 则可执行，False 含拒绝原因）
        """
        cfg      = get_signal_quality_config()
        regime_cfg = get_regime_adjusted_config(signal.regime)

        decision = FunnelDecision(
            passed     = False,
            symbol     = signal.symbol,
            signal_id  = signal.signal_id,
            regime     = signal.regime,
            concurrent_positions = current_positions_count,
            daily_signals_used   = daily_signals_executed,
        )

        # ── Layer 0: 宇宙过滤 ───────────────────────────────────────────────
        reject = self._layer0_universe(signal, cfg)
        if reject:
            decision.rejected_at_layer = 0
            decision.rejection_reason  = reject[0]
            decision.rejection_detail  = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 1: 体制门控 ────────────────────────────────────────────────
        reject = self._layer1_regime(signal, regime_cfg)
        if reject:
            decision.rejected_at_layer = 1
            decision.rejection_reason  = reject[0]
            decision.rejection_detail  = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 2: 组合预检 ────────────────────────────────────────────────
        reject = self._layer2_portfolio(
            signal, regime_cfg,
            current_positions_count,
            daily_signals_executed,
        )
        if reject:
            decision.rejected_at_layer = 2
            decision.rejection_reason  = reject[0]
            decision.rejection_detail  = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            return decision

        # ── Layer 3: 多维共振验证 ────────────────────────────────────────────
        reject = self._layer3_resonance(signal, regime_cfg)
        if reject:
            decision.rejected_at_layer = 3
            decision.rejection_reason  = reject[0]
            decision.rejection_detail  = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            await self._create_ghost_trade(decision, signal, cfg, db)
            return decision

        # ── Layer 4: 置信度校准门 ─────────────────────────────────────────────
        conviction = signal_conviction_scorer.compute(
            symbol             = signal.symbol,
            signal_direction   = signal.direction,
            regime             = signal.regime,
            composite_score    = signal.composite_score,
            aligned_count      = signal.aligned_count,
            aligned_dims       = signal.aligned_dims,
            opposing_dims      = signal.opposing_dims,
            neutral_dims       = signal.neutral_dims,
            tech_direction     = signal.tech_direction,
            fundamental_direction = signal.fundamental_direction,
            macro_score        = signal.macro_score,
            options_score      = signal.options_score,
            historical_ic      = signal.historical_ic,
            timing_quality     = signal.timing_quality,
        )
        decision.conviction = conviction

        threshold = regime_cfg.get("SIGNAL_CONFIDENCE_THRESHOLD",
                                   cfg.SIGNAL_CONFIDENCE_THRESHOLD)

        reject = self._layer4_conviction(conviction, cfg, threshold)
        if reject:
            decision.rejected_at_layer = 4
            decision.rejection_reason  = reject[0]
            decision.rejection_detail  = reject[1]
            await self._write_audit(decision, signal, cfg, db)
            await self._create_ghost_trade(decision, signal, cfg, db)
            return decision

        # ── 通过所有层 ──────────────────────────────────────────────────────
        decision.passed = True
        await self._write_audit(decision, signal, cfg, db)
        logger.info(
            f"[SignalFunnel] ✅ PASSED {signal.symbol} {signal.direction}@{signal.regime} "
            f"conviction={conviction.conviction_score:.1f}"
        )
        return decision

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
        long_allowed  = regime_cfg.get("long_allowed", True)
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
    ) -> Optional[tuple[str, str]]:
        max_pos   = regime_cfg.get("MAX_CONCURRENT_POSITIONS", 6)
        max_daily = regime_cfg.get("MAX_DAILY_SIGNALS", 5)
        max_corr  = regime_cfg.get("MAX_POSITION_CORRELATION", 0.70)

        if current_positions >= max_pos:
            return (
                RejectionReason.MAX_POSITIONS_REACHED,
                f"当前持仓数 {current_positions} 已达上限 {max_pos}",
            )
        if daily_executed >= max_daily:
            return (
                RejectionReason.DAILY_QUOTA_EXHAUSTED,
                f"今日已推进信号 {daily_executed} 个，已达日配额 {max_daily}",
            )
        if (signal.max_correlation_with_existing is not None
                and signal.max_correlation_with_existing >= max_corr):
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
        min_dims = regime_cfg.get("SIGNAL_RESONANCE_MIN_DIMS", 4)
        require_tech = regime_cfg.get("RESONANCE_REQUIRED_TECHNICAL", True)

        # 反共振  技术/基本面方向对立
        if (signal.tech_direction != 0
                and signal.fundamental_direction != 0
                and signal.tech_direction != signal.fundamental_direction):
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
                db           = db,
                symbol       = signal.symbol,
                signal_id    = signal.signal_id,
                funnel_result = FunnelResult.PASSED if decision.passed else FunnelResult.REJECTED,
                rejected_at_layer  = decision.rejected_at_layer,
                rejection_reason   = decision.rejection_reason,
                rejection_detail   = decision.rejection_detail,
                conviction         = decision.conviction,
                composite_score    = signal.composite_score * 100,
                aligned_count      = signal.aligned_count,
                aligned_dims       = signal.aligned_dims,
                opposing_dims      = signal.opposing_dims,
                neutral_dims       = signal.neutral_dims,
                anti_resonance_triggered = (
                    decision.conviction.anti_resonance_killed
                    if decision.conviction else False
                ),
                signal_direction   = signal.direction,
                regime             = signal.regime,
                concurrent_positions = decision.concurrent_positions,
                daily_signals_used   = decision.daily_signals_used,
                generated_at         = signal.generated_at,
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
        try:
            from app.services.ghost_trade_service import ghost_trade_service
            await ghost_trade_service.create_from_rejected_signal(
                db              = db,
                symbol          = signal.symbol,
                signal_id       = signal.signal_id,
                direction       = signal.direction,
                rejection_reason = decision.rejection_reason,
                rejected_at_layer = decision.rejected_at_layer,
                conviction_at_rejection = (
                    decision.conviction.conviction_score
                    if decision.conviction else None
                ),
                max_tracking_days = cfg.GHOST_TRADE_MAX_DAYS,
            )
        except Exception as e:
            logger.warning(f"[SignalFunnel] 幽灵交易创建失败（不影响主流程）: {e}")


# ── 模块级单例 ────────────────────────────────────────────────────────────────
signal_quality_funnel = SignalQualityFunnel()
