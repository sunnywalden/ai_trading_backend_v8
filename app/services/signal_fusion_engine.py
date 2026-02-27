"""V10.2-M4: 六维信号融合引擎 + 市场情绪评分

维度权重（基准）：
    technical       25%
    fundamental     20%
    macro           15%
    volume_anomaly  15%
    options         15%
    sentiment       10%

共振奖励：对齐维度数量 > 3 时，每个额外对齐维度 +5% 奖励
冲突惩罚：技术信号与基本面信号方向相反时，扣除 15%
市场状态乘数：由 regime_multiplier 调整最终置信度

情绪评分来源（SentimentScorer）：
    - 空头利率（weekly）
    - 散户情绪（daily, AI NLP）
    - 新闻情绪（real-time NLP）
    - 内部交易报告（daily SEC）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── 维度权重 ──────────────────────────────────────────────────────────────────

_DIM_WEIGHTS: dict[str, float] = {
    "technical":      0.25,
    "fundamental":    0.20,
    "macro":          0.15,
    "volume_anomaly": 0.15,
    "options":        0.15,
    "sentiment":      0.10,
}

# 市场状态乘数（CRISIS 时整体降低置信度 → 更保守）
_REGIME_MULTIPLIERS: dict[str, float] = {
    "BULL_TREND": 1.05,
    "BEAR_TREND": 0.90,
    "SIDEWAYS":   0.95,
    "HIGH_VOL":   0.88,
    "CRISIS":     0.75,
}

_RESONANCE_BONUS      = 0.05   # 每个额外对齐维度的奖励
_RESONANCE_THRESHOLD  = 3      # 超过此数量才给奖励
_CONFLICT_PENALTY     = 0.15   # 技术 vs 基本面方向冲突时惩罚


@dataclass
class DimensionScore:
    """单个维度的评分"""
    name:       str
    score:      float     # 0.0 ~ 1.0，表示看多强度（0.5 = 中性）
    weight:     float
    direction:  int       # +1 = 买入，-1 = 卖出，0 = 中性
    description: str = ""


@dataclass
class FusedSignalResult:
    """六维融合结果"""
    symbol:              str
    fused_confidence:    float              # 最终融合置信度 0-1
    base_score:          float              # 未修正的加权基础分
    resonance_bonus:     float
    conflict_penalty:    float
    regime_multiplier:   float
    regime:              str
    dimensions:          list[DimensionScore] = field(default_factory=list)
    dominant_dimension:  str = ""           # 贡献最大的维度
    aligned_count:       int = 0            # 同向维度数量
    recommendation:      str = ""           # BUY / SELL / HOLD

    def to_dict(self) -> dict:
        return {
            "symbol":             self.symbol,
            "fused_confidence":   round(self.fused_confidence, 4),
            "base_score":         round(self.base_score, 4),
            "resonance_bonus":    round(self.resonance_bonus, 4),
            "conflict_penalty":   round(self.conflict_penalty, 4),
            "regime_multiplier":  self.regime_multiplier,
            "regime":             self.regime,
            "aligned_count":      self.aligned_count,
            "dominant_dimension": self.dominant_dimension,
            "recommendation":     self.recommendation,
            "dimensions": [
                {
                    "name":      d.name,
                    "score":     round(d.score, 4),
                    "weight":    d.weight,
                    "direction": d.direction,
                    "description": d.description,
                }
                for d in self.dimensions
            ],
        }


@dataclass
class SentimentData:
    """情绪维度输入数据"""
    symbol:                  str
    short_interest_pct:      Optional[float] = None   # 空头利率 %（值越高越看空）
    retail_sentiment_score:  Optional[float] = None   # 散户情绪 0-1（0.5 中性）
    news_sentiment_score:    Optional[float] = None   # 新闻情绪 0-1
    insider_net_bought:      Optional[float] = None   # 内部人净买入（正值看涨）


class SentimentScorer:
    """
    市场情绪第六维评分器。

    合成公式（均权平均，缺项跳过）：
        raw = mean([
            1 - short_interest_pct / 30,   # 空头利率越高 → 情绪分越低
            retail_sentiment_score,
            news_sentiment_score,
            0.5 + clip(insider_net_bought / 1e6, -0.5, 0.5),
        ])
    """

    def score(self, data: SentimentData) -> DimensionScore:
        components: list[float] = []

        if data.short_interest_pct is not None:
            components.append(max(0.0, 1.0 - data.short_interest_pct / 30.0))

        if data.retail_sentiment_score is not None:
            components.append(data.retail_sentiment_score)

        if data.news_sentiment_score is not None:
            components.append(data.news_sentiment_score)

        if data.insider_net_bought is not None:
            insider_score = 0.5 + max(-0.5, min(0.5, data.insider_net_bought / 1_000_000))
            components.append(insider_score)

        if not components:
            score_val = 0.5  # 无数据时中性
            direction = 0
            desc = "no sentiment data"
        else:
            score_val = sum(components) / len(components)
            direction = 1 if score_val > 0.55 else (-1 if score_val < 0.45 else 0)
            desc = f"components={len(components)} avg={score_val:.3f}"

        return DimensionScore(
            name="sentiment",
            score=score_val,
            weight=_DIM_WEIGHTS["sentiment"],
            direction=direction,
            description=desc,
        )


class SignalFusionEngine:
    """
    六维信号融合引擎。

    使用示例::

        engine = SignalFusionEngine()
        result = engine.compute_fused_confidence(
            symbol="AAPL",
            regime="BULL_TREND",
            technical=DimensionScore("technical", 0.78, 0.25, 1, "RSI breakout"),
            fundamental=DimensionScore("fundamental", 0.65, 0.20, 1, "PEG < 1"),
            macro=DimensionScore("macro", 0.55, 0.15, 0, "neutral"),
            volume_anomaly=DimensionScore("volume_anomaly", 0.70, 0.15, 1, "3x avg volume"),
            options=DimensionScore("options", 0.60, 0.15, 1, "low IV, call skew"),
            sentiment=DimensionScore("sentiment", 0.52, 0.10, 0, "neutral"),
        )
    """

    def __init__(self) -> None:
        self._sentiment_scorer = SentimentScorer()

    def compute_fused_confidence(
        self,
        symbol: str,
        regime: str,
        technical:      Optional[DimensionScore] = None,
        fundamental:    Optional[DimensionScore] = None,
        macro:          Optional[DimensionScore] = None,
        volume_anomaly: Optional[DimensionScore] = None,
        options:        Optional[DimensionScore] = None,
        sentiment:      Optional[DimensionScore] = None,
        sentiment_data: Optional[SentimentData] = None,
    ) -> FusedSignalResult:
        """计算六维融合置信度。

        缺失维度用 0.5（中性）填充，权重重新归一化。
        """
        # ── 准备维度列表 ──────────────────────────────────────────────────────
        if sentiment is None and sentiment_data is not None:
            sentiment = self._sentiment_scorer.score(sentiment_data)

        dim_map: dict[str, Optional[DimensionScore]] = {
            "technical":      technical,
            "fundamental":    fundamental,
            "macro":          macro,
            "volume_anomaly": volume_anomaly,
            "options":        options,
            "sentiment":      sentiment,
        }

        dims: list[DimensionScore] = []
        for name, ds in dim_map.items():
            if ds is None:
                ds = DimensionScore(name=name, score=0.5, weight=_DIM_WEIGHTS[name],
                                    direction=0, description="inferred neutral")
            dims.append(ds)

        # ── Layer-1: 加权基础分 ───────────────────────────────────────────────
        total_weight = sum(d.weight for d in dims)
        base_score   = sum(d.score * d.weight for d in dims) / total_weight

        # ── Layer-2: 共振奖励 ──────────────────────────────────────────────────
        bullish_count = sum(1 for d in dims if d.direction == 1)
        bearish_count = sum(1 for d in dims if d.direction == -1)
        aligned_count = max(bullish_count, bearish_count)
        extra_aligned = max(0, aligned_count - _RESONANCE_THRESHOLD)
        resonance_bonus = extra_aligned * _RESONANCE_BONUS

        # ── Layer-3: 冲突惩罚 ─────────────────────────────────────────────────
        tech_dir = (technical.direction if technical else 0)
        fund_dir = (fundamental.direction if fundamental else 0)
        conflict_penalty = _CONFLICT_PENALTY if (tech_dir != 0 and fund_dir != 0 and tech_dir != fund_dir) else 0.0

        # ── Layer-4: 市场状态乘数 ──────────────────────────────────────────────
        regime_multiplier = _REGIME_MULTIPLIERS.get(regime, 1.0)

        # ── 最终置信度 ────────────────────────────────────────────────────────
        raw_confidence    = (base_score + resonance_bonus - conflict_penalty)
        fused_confidence  = max(0.0, min(1.0, raw_confidence * regime_multiplier))

        # ── 主导维度 ──────────────────────────────────────────────────────────
        dominant = max(dims, key=lambda d: d.score * d.weight)

        # ── 推荐 ──────────────────────────────────────────────────────────────
        if fused_confidence >= 0.65:
            recommendation = "BUY"
        elif fused_confidence <= 0.35:
            recommendation = "SELL"
        else:
            recommendation = "HOLD"

        return FusedSignalResult(
            symbol=symbol,
            fused_confidence=fused_confidence,
            base_score=base_score,
            resonance_bonus=resonance_bonus,
            conflict_penalty=conflict_penalty,
            regime_multiplier=regime_multiplier,
            regime=regime,
            dimensions=dims,
            dominant_dimension=dominant.name,
            aligned_count=aligned_count,
            recommendation=recommendation,
        )

    def score_sentiment_only(
        self,
        data: SentimentData,
    ) -> DimensionScore:
        """仅计算情绪维度评分（供独立 API 端点调用）。"""
        return self._sentiment_scorer.score(data)


# ── 模块级单例 ────────────────────────────────────────────────────────────────
signal_fusion_engine = SignalFusionEngine()
