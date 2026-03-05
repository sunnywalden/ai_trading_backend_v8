"""V10.4.2: SignalConvictionScorer — 信号信念评分引擎

Conviction Score 是信号精英化漏斗的核心评分指标，综合五个维度：

  conviction_score = (
      composite_score     * 0.40
      + resonance_bonus   * 0.25
      + regime_alignment  * 0.15
      + historical_ic     * 0.10
      + timing_quality    * 0.10
  )

其中：
  - composite_score  : 来自 SignalFusionEngine 的六维加权融合分（映射到 0-100）
  - resonance_bonus  : 同向维度数量的阶梯奖励（aligned_count 5→90, 4→70, 3→30, ≤2→0）
  - regime_alignment : 当前市场体制与信号方向的匹配度（0-100）
  - historical_ic    : 该标的在当前策略下的历史信息系数（0-100）；IC 不可用时退化为 0
  - timing_quality   : 信号时机质量，基于 Alpha Decay 曲线位置（0-100）

Anti-resonance Kill Switch：
  - 技术面与基本面方向对立 → conviction_score 强制归零
  - CRISIS 体制做多 → conviction_score 强制归零
  - 宏观分 < 30 且做多 → conviction_score 强制归零
  - 期权分 < 20 且做多 → conviction_score 强制归零
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 共振奖励阶梯 ──────────────────────────────────────────────────────────────
_RESONANCE_BONUS_TABLE: dict[int, float] = {
    6: 100.0,   # 完美共振（极罕见）
    5: 90.0,    # 强共振
    4: 70.0,    # 达标共振（最低可接受）
    3: 30.0,    # 弱共振（通常被 Layer 3 拒绝）
    2: 0.0,
    1: 0.0,
    0: 0.0,
}

# ── 体制与方向匹配分 ──────────────────────────────────────────────────────────
_REGIME_ALIGNMENT_MAP: dict[tuple[str, str], float] = {
    ("BULL_TREND", "LONG"):  100.0,
    ("BULL_TREND", "SHORT"):  30.0,
    ("SIDEWAYS",   "LONG"):   60.0,
    ("SIDEWAYS",   "SHORT"):  60.0,
    ("BEAR_TREND", "LONG"):   20.0,
    ("BEAR_TREND", "SHORT"): 100.0,
    ("HIGH_VOL",   "LONG"):   45.0,
    ("HIGH_VOL",   "SHORT"):  70.0,
    ("CRISIS",     "LONG"):    0.0,  # CRISIS 做多视为极不对齐
    ("CRISIS",     "SHORT"):  85.0,
}

# ── Conviction Score 各组件权重 ───────────────────────────────────────────────
_WEIGHTS = {
    "composite":        0.40,
    "resonance_bonus":  0.25,
    "regime_alignment": 0.15,
    "historical_ic":    0.10,
    "timing_quality":   0.10,
}


@dataclass
class ConvictionComponents:
    """Conviction Score 各组件明细（用于 API 返回和审计日志）"""
    composite_score:         float
    resonance_bonus:         float       # 0-100
    regime_alignment:        float       # 0-100
    historical_ic_bonus:     float       # 0-100，IC 不可用时为 0
    timing_quality:          float       # 0-100
    anti_resonance_killed:   bool = False
    kill_reason:             str  = ""

    # 最终分
    conviction_score:        float = 0.0
    calibrated_lower_bound:  float = 0.0  # 保守估计校准下界

    # 参考信息
    aligned_count:           int = 0
    aligned_dims:            list[str] = field(default_factory=list)
    opposing_dims:           list[str] = field(default_factory=list)
    neutral_dims:            list[str] = field(default_factory=list)
    regime:                  str = ""
    signal_direction:        str = ""

    def to_dict(self) -> dict:
        return {
            "conviction_score":        round(self.conviction_score, 2),
            "calibrated_lower_bound":  round(self.calibrated_lower_bound, 2),
            "components": {
                "composite_score":     round(self.composite_score, 2),
                "resonance_bonus":     round(self.resonance_bonus, 2),
                "regime_alignment":    round(self.regime_alignment, 2),
                "historical_ic_bonus": round(self.historical_ic_bonus, 2),
                "timing_quality":      round(self.timing_quality, 2),
            },
            "weights": _WEIGHTS,
            "anti_resonance_killed":   self.anti_resonance_killed,
            "kill_reason":             self.kill_reason,
            "resonance": {
                "aligned_count":  self.aligned_count,
                "aligned_dims":   self.aligned_dims,
                "opposing_dims":  self.opposing_dims,
                "neutral_dims":   self.neutral_dims,
            },
            "regime":           self.regime,
            "signal_direction": self.signal_direction,
        }


class SignalConvictionScorer:
    """
    信号信念评分引擎。

    计算 Conviction Score（0-100），作为 Layer 4（置信度校准门）的门控依据。
    """

    def compute(
        self,
        *,
        symbol: str,
        signal_direction: str,       # "LONG" / "SHORT"
        regime: str,                 # 当前市场体制
        # ── 来自 SignalFusionEngine 的数据 ──
        composite_score: float,      # 六维加权融合分，0-1（内部会 *100）
        aligned_count: int,          # 同向维度数量
        aligned_dims: list[str],
        opposing_dims: list[str],
        neutral_dims:  list[str],
        tech_direction: int,         # +1 / -1 / 0
        fundamental_direction: int,  # +1 / -1 / 0
        macro_score: float,          # 0-1
        options_score: float,        # 0-1
        # ── 可选增强数据 ──
        historical_ic: Optional[float] = None,  # 历史 IC（0-1），None → 缺失
        timing_quality: Optional[float] = None, # 时机质量（0-1），None → 中性 0.5
        # ── 校准参数（可选，用于计算校准下界）──
        confidence_std: float = 5.0, # 置信度估计的标准差（百分点）
    ) -> ConvictionComponents:
        """
        计算 Conviction Score 及各组件。

        Returns:
            ConvictionComponents 对象（含 conviction_score 和各细项分解）
        """
        # ── Step 1: 反共振一票否决检查 ──────────────────────────────────────
        kill_flag   = False
        kill_reason = ""

        if (tech_direction != 0  # 技术有明确方向
                and fundamental_direction != 0  # 基本面有明确方向
                and tech_direction != fundamental_direction):
            kill_flag   = True
            kill_reason = f"TECH_FUND_CONFLICT: tech={tech_direction} fundamental={fundamental_direction}"

        elif regime == "CRISIS" and signal_direction == "LONG":
            kill_flag   = True
            kill_reason = "CRISIS_LONG_BLOCK: 危机体制禁止做多"

        elif macro_score < 0.30 and signal_direction == "LONG":
            kill_flag   = True
            kill_reason = f"MACRO_BEARISH_LONG: macro_score={macro_score:.2f} < 0.30"

        elif options_score < 0.20 and signal_direction == "LONG":
            kill_flag   = True
            kill_reason = f"OPTIONS_BEARISH_LONG: options_score={options_score:.2f} < 0.20"

        if kill_flag:
            logger.info(f"[ConvictionScorer] {symbol} ANTI-RESONANCE KILL: {kill_reason}")
            return ConvictionComponents(
                composite_score       = composite_score * 100,
                resonance_bonus       = 0.0,
                regime_alignment      = 0.0,
                historical_ic_bonus   = 0.0,
                timing_quality        = 0.0,
                anti_resonance_killed = True,
                kill_reason           = kill_reason,
                conviction_score      = 0.0,
                calibrated_lower_bound = 0.0,
                aligned_count         = aligned_count,
                aligned_dims          = aligned_dims,
                opposing_dims         = opposing_dims,
                neutral_dims          = neutral_dims,
                regime                = regime,
                signal_direction      = signal_direction,
            )

        # ── Step 2: 计算各组件（均映射到 0-100） ────────────────────────────
        comp_100 = min(100.0, composite_score * 100.0)

        # 共振奖励阶梯
        res_bonus = _RESONANCE_BONUS_TABLE.get(aligned_count, 0.0)

        # 体制匹配度
        regime_align = _REGIME_ALIGNMENT_MAP.get((regime, signal_direction), 50.0)

        # 历史 IC 奖励（IC 不可用时退化为 0，分母重新归一化）
        ic_bonus = (min(100.0, max(0.0, historical_ic * 100.0))
                    if historical_ic is not None else 0.0)
        ic_available = historical_ic is not None

        # 时机质量（0.5 默认中性 = 50分）
        timing = (timing_quality if timing_quality is not None else 0.5) * 100.0

        # ── Step 3: 加权求和（历史 IC 不可用时重新归一化权重）────────────────
        if ic_available:
            weights = _WEIGHTS
        else:
            # 把 historical_ic 的 10% 权重分摊给 composite 和 resonance_bonus
            weights = {
                "composite":        0.45,
                "resonance_bonus":  0.28,
                "regime_alignment": 0.17,
                "historical_ic":    0.00,
                "timing_quality":   0.10,
            }

        conviction = (
            comp_100      * weights["composite"]
            + res_bonus   * weights["resonance_bonus"]
            + regime_align * weights["regime_alignment"]
            + ic_bonus    * weights["historical_ic"]
            + timing      * weights["timing_quality"]
        )
        conviction = max(0.0, min(100.0, conviction))

        # ── Step 4: 校准下界（保守估计）────────────────────────────────────
        calibrated_lb = max(0.0, conviction - confidence_std)

        logger.debug(
            f"[ConvictionScorer] {symbol} {signal_direction}@{regime}: "
            f"conviction={conviction:.1f} (comp={comp_100:.1f}, "
            f"res={res_bonus:.0f}, regime_align={regime_align:.0f}, "
            f"ic={ic_bonus:.0f}, timing={timing:.0f})"
        )

        return ConvictionComponents(
            composite_score        = comp_100,
            resonance_bonus        = res_bonus,
            regime_alignment       = regime_align,
            historical_ic_bonus    = ic_bonus,
            timing_quality         = timing,
            anti_resonance_killed  = False,
            kill_reason            = "",
            conviction_score       = conviction,
            calibrated_lower_bound = calibrated_lb,
            aligned_count          = aligned_count,
            aligned_dims           = aligned_dims,
            opposing_dims          = opposing_dims,
            neutral_dims           = neutral_dims,
            regime                 = regime,
            signal_direction       = signal_direction,
        )


# ── 模块级单例 ────────────────────────────────────────────────────────────────
signal_conviction_scorer = SignalConvictionScorer()
