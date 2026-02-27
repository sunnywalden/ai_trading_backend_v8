"""V10.2-M4: 六维信号融合 API 路由

Endpoints:
  POST /api/v1/signals/fuse       → 计算六维融合置信度
  POST /api/v1/signals/sentiment  → 仅计算情绪维度评分
"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.signals import (
    FusedSignalRequest,
    FusedSignalResponse,
    DimensionScoreItem,
    SentimentScoreResponse,
)
from app.services.signal_fusion_engine import (
    DimensionScore,
    SentimentData,
    signal_fusion_engine,
)

router = APIRouter(prefix="/api/v1/signals", tags=["Signal Fusion"])


def _make_dim(name: str, score: float | None, default: float = 0.5) -> DimensionScore:
    """构造单维度评分对象（缺省按中性处理）。"""
    s = score if score is not None else default
    direction = 1 if s > 0.55 else (-1 if s < 0.45 else 0)
    return DimensionScore(
        name=name,
        score=s,
        weight=0.0,   # 权重由引擎内部覆盖
        direction=direction,
        description="api_provided",
    )


@router.post("/fuse", response_model=FusedSignalResponse, summary="计算六维融合置信度")
async def compute_fused_signal(body: FusedSignalRequest):
    """
    传入各维度原始评分（0-1）+ 情绪原始数据 + 当前市场状态，
    返回融合置信度及分解详情。

    缺失维度默认设为中性 0.5。
    """
    sentiment_data = SentimentData(
        symbol=body.symbol,
        short_interest_pct=body.short_interest_pct,
        retail_sentiment_score=body.retail_sentiment,
        news_sentiment_score=body.news_sentiment,
        insider_net_bought=body.insider_net_bought,
    )

    result = signal_fusion_engine.compute_fused_confidence(
        symbol=body.symbol,
        regime=body.regime,
        technical=_make_dim("technical", body.technical_score) if body.technical_score is not None else None,
        fundamental=_make_dim("fundamental", body.fundamental_score) if body.fundamental_score is not None else None,
        macro=_make_dim("macro", body.macro_score) if body.macro_score is not None else None,
        volume_anomaly=_make_dim("volume_anomaly", body.volume_anomaly_score) if body.volume_anomaly_score is not None else None,
        options=_make_dim("options", body.options_score) if body.options_score is not None else None,
        sentiment_data=sentiment_data,
    )

    dims = [
        DimensionScoreItem(
            name=d.name, score=d.score, weight=d.weight,
            direction=d.direction, description=d.description,
        )
        for d in result.dimensions
    ]

    return FusedSignalResponse(
        symbol=result.symbol,
        fused_confidence=result.fused_confidence,
        base_score=result.base_score,
        resonance_bonus=result.resonance_bonus,
        conflict_penalty=result.conflict_penalty,
        regime_multiplier=result.regime_multiplier,
        regime=result.regime,
        aligned_count=result.aligned_count,
        dominant_dimension=result.dominant_dimension,
        recommendation=result.recommendation,
        dimensions=dims,
    )


@router.post("/sentiment/{symbol}", response_model=SentimentScoreResponse, summary="计算情绪维度评分")
async def compute_sentiment(
    symbol: str,
    short_interest_pct: float | None = None,
    retail_sentiment:   float | None = None,
    news_sentiment:     float | None = None,
    insider_net_bought: float | None = None,
):
    """仅返回情绪维度评分（0-1），用于独立情绪监控面板。"""
    data = SentimentData(
        symbol=symbol,
        short_interest_pct=short_interest_pct,
        retail_sentiment_score=retail_sentiment,
        news_sentiment_score=news_sentiment,
        insider_net_bought=insider_net_bought,
    )
    dim = signal_fusion_engine.score_sentiment_only(data)
    components_used = sum([
        short_interest_pct is not None,
        retail_sentiment is not None,
        news_sentiment is not None,
        insider_net_bought is not None,
    ])
    return SentimentScoreResponse(
        symbol=symbol,
        score=dim.score,
        direction=dim.direction,
        description=dim.description,
        components_used=components_used,
    )
