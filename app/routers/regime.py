"""V10.2-M1: 市场体制感知 API 路由

端点：
  GET  /api/v1/regime/current           — 查询当前有效体制（含置信度和五维得分）
  GET  /api/v1/regime/history           — 分页体制历史记录
  GET  /api/v1/regime/strategy-weights  — 当前体制下各策略类别权重倍数
  POST /api/v1/regime/override          — 管理员手动覆写当前体制
  POST /api/v1/regime/classify          — 管理员手动触发立即重新分类（V10.5.1）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.models.db import get_session
from app.models.market_regime import MarketRegime, RegimeType
from app.schemas.regime import (RegimeClassifyResponse, RegimeCurrentResponse,
                                RegimeHistoryResponse, RegimeOverrideRequest,
                                RegimeOverrideResponse, RegimeResponse,
                                RegimeScoresSchema, RegimeStrategyWeightSchema,
                                RegimeStrategyWeightsResponse)
from app.services.regime_classifier import (RegimeClassifier,
                                            _parse_var_multipliers)
from app.services.regime_strategy_allocator import (
    fetch_current_regime_from_redis, fetch_regime_weights_from_redis,
    get_regime_strategy_weights)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/regime", tags=["市场体制感知 V10.2"])


def _orm_to_schema(r: MarketRegime) -> RegimeResponse:
    """将 ORM 对象转换为响应 Schema。"""
    return RegimeResponse(
        id=r.id,
        regime=r.regime,
        prev_regime=r.prev_regime,
        confidence=round(r.confidence or 0.0, 4),
        classification_date=r.classification_date,
        valid_from=r.valid_from,
        valid_until=r.valid_until,
        scores=RegimeScoresSchema(
            trend=r.trend_score,
            vol=r.vol_score,
            breadth=r.breadth_score,
            macro=r.macro_score,
            momentum=r.momentum_score,
        ),
        reasoning=r.reasoning,
        is_override=r.is_override,
        override_by=r.override_by,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /current
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/current",
    response_model=RegimeCurrentResponse,
    summary="当前市场体制",
    description="查询系统最新确认的市场体制分类及五维得分（含 VaR 倍数）。",
)
async def get_current_regime(
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
) -> RegimeCurrentResponse:
    current = await RegimeClassifier.get_current_regime(db)

    if current is None:
        # 尚无体制记录 → 返回「未知」占位响应（不报错）
        logger.info("[RegimeRouter] No regime history found; returning UNKNOWN placeholder")
        placeholder = RegimeResponse(
            regime="UNKNOWN",
            confidence=0.0,
            is_override=False,
            reasoning="体制感知引擎尚未运行，请等待每日 08:00 自动分类。",
        )
        return RegimeCurrentResponse(regime=placeholder, var_multiplier=1.0, from_cache=False)

    return RegimeCurrentResponse(
        regime=_orm_to_schema(current),
        var_multiplier=_parse_var_multipliers().get(current.regime, 1.0),
        from_cache=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    response_model=RegimeHistoryResponse,
    summary="体制历史记录",
    description="分页获取历史体制切换记录，按时间降序排列。",
)
async def get_regime_history(
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
) -> RegimeHistoryResponse:
    offset = (page - 1) * size
    items, total = await RegimeClassifier.get_regime_history(db, limit=size, offset=offset)

    import math
    pages = math.ceil(total / size) if total > 0 else 1

    return RegimeHistoryResponse(
        regimes=[_orm_to_schema(r) for r in items],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /strategy-weights
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/strategy-weights",
    response_model=RegimeStrategyWeightsResponse,
    summary="当前体制下策略权重倍数",
    description=(
        "返回当前市场体制下各策略类别（TREND/MOMENTUM/MEAN_REV/LOW_VOL 等）的权重倍数。"
        "倍数 > 1.0 表示该体制下此类策略超配，< 1.0 表示减配。"
    ),
)
async def get_strategy_weights(
    db: AsyncSession = Depends(get_session),
    _user: str = Depends(get_current_user),
) -> RegimeStrategyWeightsResponse:
    # 优先从 Redis 读（快速），回退到 DB 查询
    try:
        redis_info = await fetch_current_regime_from_redis()
        current_regime_str = redis_info.get("regime", "UNKNOWN")

        if current_regime_str == "UNKNOWN":
            raise ValueError("Redis regime unknown, falling back to DB")

        weights = await fetch_regime_weights_from_redis()
    except Exception:
        # Fallback: 从 DB 查最新体制
        current = await RegimeClassifier.get_current_regime(db)
        if current is None:
            current_regime_str = "RANGE_BOUND"
        else:
            current_regime_str = current.regime

        weights = get_regime_strategy_weights(current_regime_str)

    # 适配前端格式：从 dict 转换为 list
    weights_list = [
        RegimeStrategyWeightSchema(style=style, weight=weight, baseline=1.0)
        for style, weight in weights.items()
    ]

    return RegimeStrategyWeightsResponse(
        regime=current_regime_str,
        weights=weights_list,
        updated_at=datetime.now(tz=timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /override
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/override",
    response_model=RegimeOverrideResponse,
    summary="手动覆写当前体制（管理员）",
    description=(
        "管理员强制覆写当前市场体制（如系统未能正确识别突发行情时）。"
        "覆写会立即触发 REGIME_CHANGED 事件，更新 RiskGate VaR 倍数及策略权重。"
    ),
)
async def override_regime(
    payload: RegimeOverrideRequest = Body(...),
    db: AsyncSession = Depends(get_session),
    user: str = Depends(get_current_user),
) -> RegimeOverrideResponse:
    # 验证体制值
    valid_regimes = {e.value for e in RegimeType}
    if payload.regime.upper() not in valid_regimes:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid regime '{payload.regime}'. Must be one of: {sorted(valid_regimes)}",
        )

    target_regime = payload.regime.upper()
    now_utc = datetime.now(tz=timezone.utc)
    operator = user if user else "admin"

    try:
        # 封存当前体制
        await _close_regime_static(db, now_utc)

        # 写入覆写记录
        new_regime = MarketRegime(
            classification_date=now_utc,
            valid_from=now_utc,
            valid_until=None,
            regime=target_regime,
            prev_regime=None,
            confidence=1.0,
            reasoning=f"[人工覆写] 操作者: {operator}. 原因: {payload.reason or '未填写'}",
            is_override=True,
            override_by=operator,
        )
        db.add(new_regime)
        await db.commit()
        await db.refresh(new_regime)

        # 触发 REGIME_CHANGED 事件（立即更新 RiskGate + Redis）
        from app.core.event_bus import Topics, event_bus
        from app.services.regime_classifier import _parse_var_multipliers
        await event_bus.publish(
            Topics.REGIME_CHANGED,
            {
                "prev": None,
                "curr": target_regime,
                "confidence": 1.0,
                "regime_id": new_regime.id,
                "var_multiplier": _parse_var_multipliers().get(target_regime, 1.0),
            },
        )

        logger.info(
            f"[RegimeRouter] Manual override by {operator}: regime set to {target_regime}"
        )
        return RegimeOverrideResponse(
            success=True,
            message=f"Market regime manually overridden to {target_regime}",
            regime=_orm_to_schema(new_regime),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[RegimeRouter] Override failed: {exc}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Override failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: 静态封存当前体制（供 override 用）
# ─────────────────────────────────────────────────────────────────────────────

async def _close_regime_static(db: AsyncSession, close_time: datetime) -> None:
    """封存当前有效体制（valid_until = close_time）。"""
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(MarketRegime)
        .where(MarketRegime.valid_until.is_(None))
        .values(valid_until=close_time)
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /classify  (V10.5.1)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/classify",
    response_model=RegimeClassifyResponse,
    summary="立即触发体制重新分类（管理员）",
    description=(
        "跳过每日 cron 时间限制，立即执行一次市场体制分类。"
        "体制不变时刷新 classification_date（消除陈旧告警），体制切换时写入新记录并广播事件。"
        "需要管理员权限。"
    ),
)
async def trigger_classify(
    db: AsyncSession = Depends(get_session),
    user: str = Depends(get_current_user),
) -> RegimeClassifyResponse:
    logger.info(f"[RegimeRouter] Manual classify triggered by {user}")
    try:
        from app.services.regime_classifier import regime_classifier

        result = await regime_classifier.run(db)

        current = await RegimeClassifier.get_current_regime(db)
        regime_schema = _orm_to_schema(current) if current else None

        confirmed = result.get("confirmed", False)
        candidate = result.get("candidate")
        confidence = result.get("confidence", 0.0)

        if confirmed:
            message = f"体制已切换至 {candidate}（置信度 {confidence:.1%}）"
        else:
            message = f"体制未变（{candidate}），已刷新 classification_date"

        logger.info(f"[RegimeRouter] Manual classify complete: {message}")
        return RegimeClassifyResponse(
            success=True,
            message=message,
            candidate=candidate,
            confirmed=confirmed,
            confidence=round(confidence, 4),
            regime=regime_schema,
        )

    except Exception as exc:
        logger.error(f"[RegimeRouter] Manual classify failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Classification failed: {exc}")
