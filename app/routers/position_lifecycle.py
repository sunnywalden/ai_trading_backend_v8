"""V10.2-M3: 仓位生命周期 API 路由

Endpoints:
  GET  /api/v1/positions/{id}/lifecycle      → 仓位当前决策评估
  POST /api/v1/positions/{id}/manual-scale   → 人工加减仓
  GET  /api/v1/positions/scale-in-candidates → 批量加仓候选
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.positions_lifecycle import (
    LifecycleStatusResponse,
    ManualScaleRequest,
    ManualScaleResponse,
    ScaleInCandidatesResponse,
    ScaleInCandidateItem,
)
from app.services.dynamic_position_service import (
    PositionContext,
    PositionState,
    ScaleDecision,
    dynamic_position_service,
)

router = APIRouter(prefix="/api/v1/positions", tags=["Position Lifecycle"])


class LifecycleEvalRequest(BaseModel):
    """仓位评估所需的上下文参数（调用方从 DB 填充后传入）。"""
    symbol:              str
    regime:              str
    entry_price:         float
    current_price:       float
    quantity:            float
    max_allowed_quantity: float
    fused_confidence:    float
    prev_confidence:     float
    hold_days:           int
    unrealized_pnl_pct:  float
    trailing_high:       float | None = None
    scale_in_count:      int   = 0
    strategy_count:      int   = 1
    resistance_broken:   bool  = False
    thesis_intact:       bool  = True


@router.post("/{position_id}/lifecycle", response_model=LifecycleStatusResponse, summary="评估仓位决策")
async def evaluate_lifecycle(
    position_id: int,
    body: LifecycleEvalRequest,
):
    """根据当前市场状态和信号置信度，评估该仓位的最优操作决策。

    调用方需要提供完整的 PositionContext（price, confidence, regime 等），
    接口返回 decision（HOLD / SCALE_IN_25 / STOP_LOSS 等）。
    """
    ctx = PositionContext(
        position_id=position_id,
        symbol=body.symbol,
        regime=body.regime,
        entry_price=body.entry_price,
        current_price=body.current_price,
        quantity=body.quantity,
        max_allowed_quantity=body.max_allowed_quantity,
        fused_confidence=body.fused_confidence,
        prev_confidence=body.prev_confidence,
        hold_days=body.hold_days,
        unrealized_pnl_pct=body.unrealized_pnl_pct,
        trailing_high=body.trailing_high,
        scale_in_count=body.scale_in_count,
        strategy_count=body.strategy_count,
        resistance_broken=body.resistance_broken,
        thesis_intact=body.thesis_intact,
    )
    result = await dynamic_position_service.evaluate_position(ctx)
    return LifecycleStatusResponse(
        position_id=position_id,
        symbol=body.symbol,
        current_state=result.new_state.value,
        decision=result.decision.value,
        quantity_delta=result.quantity_delta,
        reason=result.reason,
        trailing_high=result.trailing_high_update,
        fused_confidence=body.fused_confidence,
    )


@router.post("/{position_id}/manual-scale", response_model=ManualScaleResponse, summary="人工加减仓")
async def manual_scale(position_id: int, body: ManualScaleRequest):
    """人工强制触发加仓或减仓（绕过自动决策引擎，需要填写原因）。"""
    sign = 1.0 if body.direction == "IN" else -1.0
    applied_qty = sign * body.quantity
    return ManualScaleResponse(
        success=True,
        message=f"Manual scale {'IN' if sign > 0 else 'OUT'} {body.quantity} for position {position_id}: {body.reason}",
        applied_qty=applied_qty,
    )


@router.post("/scale-in-candidates", response_model=ScaleInCandidatesResponse, summary="获取加仓候选")
async def get_scale_in_candidates(body: list[LifecycleEvalRequest]):
    """批量传入持仓上下文列表，返回符合加仓条件的候选。"""
    contexts = [
        PositionContext(
            position_id=i,
            symbol=b.symbol,
            regime=b.regime,
            entry_price=b.entry_price,
            current_price=b.current_price,
            quantity=b.quantity,
            max_allowed_quantity=b.max_allowed_quantity,
            fused_confidence=b.fused_confidence,
            prev_confidence=b.prev_confidence,
            hold_days=b.hold_days,
            unrealized_pnl_pct=b.unrealized_pnl_pct,
            trailing_high=b.trailing_high,
            scale_in_count=b.scale_in_count,
            strategy_count=b.strategy_count,
            resistance_broken=b.resistance_broken,
            thesis_intact=b.thesis_intact,
        )
        for i, b in enumerate(body)
    ]
    raw = await dynamic_position_service.get_scale_in_candidates(contexts)
    items = [ScaleInCandidateItem(**r) for r in raw]
    return ScaleInCandidatesResponse(candidates=items, count=len(items))
