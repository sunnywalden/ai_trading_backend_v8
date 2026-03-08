"""V10.2-M1: 市场体制 Pydantic 响应模式"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RegimeScoresSchema(BaseModel):
    trend:    Optional[float] = Field(None, description="趋势强度 0~100")
    vol:      Optional[float] = Field(None, description="波动率制度 0~100（越高越恐慌）")
    breadth:  Optional[float] = Field(None, description="市场广度 0~100")
    macro:    Optional[float] = Field(None, description="宏观环境 0~100")
    momentum: Optional[float] = Field(None, description="价格动量 0~100")


class RegimeResponse(BaseModel):
    id: Optional[int] = None
    regime: str               = Field(..., description="BULL_TREND/BEAR_TREND/HIGH_VOL/MEAN_REVERT/RANGE_BOUND/CRISIS")
    prev_regime: Optional[str] = None
    confidence: float         = Field(..., ge=0, le=1, description="分类置信度 [0,1]")
    classification_date: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    scores: Optional[RegimeScoresSchema] = None
    reasoning: Optional[str] = None
    is_override: bool = False
    override_by: Optional[str] = None

    class Config:
        from_attributes = True


class RegimeHistoryResponse(BaseModel):
    """V10.2-M1: 体制历史响应（匹配前端 API）"""
    regimes: list[RegimeResponse]
    total: int
    page:  int
    size:  int
    pages: int = 1


class RegimeCurrentResponse(BaseModel):
    """V10.2-M1: 当前体制响应（含 VaR 倍数）"""
    regime: Optional[RegimeResponse] = None
    var_multiplier: float = 1.0
    from_cache: bool = False


class RegimeStrategyWeightsResponse(BaseModel):
    """V10.2-M1: 策略权重响应（前端展示用）"""
    regime: str
    weights: list[RegimeStrategyWeightSchema]
    updated_at: Optional[datetime] = None


class RegimeStrategyWeightSchema(BaseModel):
    style: str
    weight: float
    baseline: float = 1.0


class RegimeOverrideRequest(BaseModel):
    regime: str = Field(
        ...,
        description="目标体制（BULL_TREND/BEAR_TREND/HIGH_VOL/MEAN_REVERT/RANGE_BOUND/CRISIS）",
    )
    reason: Optional[str] = Field(None, description="人工覆写原因")


class RegimeOverrideResponse(BaseModel):
    """V10.2-M1: 覆写操作响应"""
    success: bool
    message: str
    regime: RegimeResponse


class RegimeClassifyResponse(BaseModel):
    """V10.5.1: 手动触发体制分类响应"""
    success: bool
    message: str
    candidate: Optional[str] = Field(None, description="分类器候选体制")
    confirmed: Optional[bool] = Field(None, description="是否确认切换（False=体制不变，仍刷新时间戳）")
    confidence: Optional[float] = Field(None, description="分类置信度 [0,1]")
    regime: Optional[RegimeResponse] = Field(None, description="操作后的当前体制记录")
