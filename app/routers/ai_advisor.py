"""
AI 交易决策 API - 统一的智能交易入口

合并原「交易助手」和「执行中心」，提供 AI 驱动的交易决策能力。

核心接口:
- POST /evaluate    多标的 AI 评估
- POST /execute     执行 AI 决策
- GET  /plans       交易计划管理
- GET  /history     决策历史
"""

from typing import Optional, List, Callable
from fastapi import APIRouter, Depends, HTTPException, Query
from app.i18n import get_translator, get_locale
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.models.db import get_session
from app.services.ai_trade_advisor_service import AITradeAdvisorService
from app.services.trading_plan_service import TradingPlanService
from app.core.config import settings

router = APIRouter(prefix="/api/v1/ai-advisor", tags=["AI Trading Advisor"])


# ==================== 请求/响应模型 ====================

class EvaluateRequest(BaseModel):
    """AI 评估请求"""
    symbols: List[str] = Field(..., min_length=1, max_length=10, description="标的列表，最多10个")
    account_id: Optional[str] = Field(None, description="账户ID")


class ExecuteRequest(BaseModel):
    """执行 AI 决策请求"""
    items: List[dict] = Field(..., description="待执行的决策列表 [{symbol, decision}]")
    execution_mode: str = Field(default="LIMIT", description="LIMIT / MARKET / PLAN")
    account_id: Optional[str] = Field(None, description="账户ID")


class PlanCreateRequest(BaseModel):
    """创建交易计划"""
    symbol: str
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    target_position: float = Field(gt=0, le=1)
    notes: Optional[str] = None


class PlanUpdateRequest(BaseModel):
    """更新交易计划"""
    entry_price: Optional[float] = Field(None, gt=0)
    stop_loss: Optional[float] = Field(None, gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    target_position: Optional[float] = Field(None, gt=0, le=1)
    plan_status: Optional[str] = None
    notes: Optional[str] = None


# ==================== AI 评估与决策 ====================

@router.post("/evaluate", summary="AI 多维度评估标的")
async def evaluate_symbols(
    request: EvaluateRequest,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator),
    locale: str = Depends(get_locale)
):
    """
    对一组标的进行 AI 多维度评估。

    流程：实时价格 + 技术面 + 基本面 + K线分析 → AI 综合研判

    返回每个标的的：
    - 多维评分
    - AI 交易决策（方向、置信度、入场价、止损、止盈、仓位）
    - 决策理由和关键因子
    """
    svc = AITradeAdvisorService(session)
    evaluations = await svc.evaluate_symbols(
        symbols=request.symbols,
        account_id=request.account_id,
        locale=locale
    )
    return {"status": "ok", "evaluations": evaluations}


@router.post("/execute", summary="执行 AI 交易决策")
async def execute_decisions(
    request: ExecuteRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    执行一个或多个 AI 决策。

    支持三种模式：
    - LIMIT: 限价单（使用 AI 建议入场价）
    - MARKET: 市价单
    - PLAN: 仅创建交易计划
    """
    svc = AITradeAdvisorService(session)
    result = await svc.batch_execute(
        decisions=request.items,
        account_id=request.account_id,
        execution_mode=request.execution_mode,
    )
    return result


# ==================== 交易计划管理（整合原交易助手） ====================

@router.get("/plans", summary="获取交易计划列表")
async def list_plans(
    status: Optional[str] = Query(None, description="ACTIVE/EXECUTED/CANCELLED/FAILED"),
    symbol: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """获取交易计划列表（分页）"""
    svc = TradingPlanService(session)
    account_id = settings.TIGER_ACCOUNT

    try:
        result = await svc.get_plans_with_pagination(
            account_id=account_id,
            status=status,
            symbol=symbol,
            page=page,
            page_size=page_size,
        )
        return result
    except Exception as e:
        # 兼容旧版 TradingPlanService
        plans = await svc.list_plans(account_id)
        filtered = plans
        if status:
            filtered = [p for p in filtered if p.plan_status == status]
        if symbol:
            filtered = [p for p in filtered if symbol.upper() in p.symbol.upper()]

        start = (page - 1) * page_size
        paged = filtered[start:start + page_size]
        return {
            "plans": [_plan_to_dict(p) for p in paged],
            "total": len(filtered),
            "page": page,
            "page_size": page_size,
        }


@router.get("/plans/{plan_id}", summary="获取计划详情")
async def get_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    svc = TradingPlanService(session)
    try:
        plan = await svc.get_plan_by_id(plan_id)
    except Exception:
        plan = None

    if not plan:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    return _plan_to_dict(plan)


@router.post("/plans", summary="创建交易计划")
async def create_plan(
    request: PlanCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    from decimal import Decimal
    svc = TradingPlanService(session)
    plan = await svc.create_plan(
        account_id=settings.TIGER_ACCOUNT,
        payload={
            "symbol": request.symbol.upper(),
            "entry_price": Decimal(str(request.entry_price)),
            "stop_loss": Decimal(str(request.stop_loss)),
            "take_profit": Decimal(str(request.take_profit)),
            "target_position": Decimal(str(request.target_position)),
            "notes": request.notes,
        }
    )
    await session.commit()
    return {"status": "ok", "plan": _plan_to_dict(plan)}


@router.put("/plans/{plan_id}", summary="更新交易计划")
async def update_plan(
    plan_id: int,
    request: PlanUpdateRequest,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    svc = TradingPlanService(session)
    payload = request.dict(exclude_none=True)
    plan = await svc.update_plan(plan_id=plan_id, payload=payload)
    if not plan:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    await session.commit()
    return {"status": "ok", "plan": _plan_to_dict(plan)}


@router.delete("/plans/{plan_id}", summary="删除交易计划")
async def delete_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    svc = TradingPlanService(session)
    ok = await svc.delete_plan(plan_id)
    if not ok:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    await session.commit()
    return {"status": "ok", "message": "Plan deleted"}


@router.post("/plans/{plan_id}/execute", summary="执行交易计划")
async def execute_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """执行单个交易计划"""
    svc = TradingPlanService(session)
    try:
        result = await svc.execute_plan(plan_id)
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plans/{plan_id}/cancel", summary="取消交易计划")
async def cancel_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    svc = TradingPlanService(session)
    try:
        result = await svc.cancel_plan(plan_id)
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 统计 ====================

@router.get("/stats", summary="获取决策统计")
async def get_stats(
    session: AsyncSession = Depends(get_session),
):
    """获取 AI 交易决策模块的统计数据"""
    svc = TradingPlanService(session)
    account_id = settings.TIGER_ACCOUNT
    try:
        plans = await svc.list_plans(account_id)
    except Exception:
        plans = []

    total = len(plans)
    active = sum(1 for p in plans if p.plan_status == "ACTIVE")
    executed = sum(1 for p in plans if p.plan_status == "EXECUTED")
    failed = sum(1 for p in plans if p.plan_status == "FAILED")
    cancelled = sum(1 for p in plans if p.plan_status == "CANCELLED")

    return {
        "total": total,
        "active": active,
        "executed": executed,
        "failed": failed,
        "cancelled": cancelled,
    }


# ==================== 评估历史管理 ====================

@router.get("/history", summary="获取评估历史")
async def get_evaluation_history(
    account_id: Optional[str] = Query(None, description="账户ID"),
    limit: int = Query(50, ge=1, le=200, description="返回记录数"),
    symbol: Optional[str] = Query(None, description="筛选标的"),
    session: AsyncSession = Depends(get_session),
):
    """
    获取 AI 评估历史记录
    
    支持按标的筛选，默认返回最近50条
    """
    svc = AITradeAdvisorService(session)
    acc_id = account_id or settings.TIGER_ACCOUNT
    
    history = await svc.get_evaluation_history(
        account_id=acc_id,
        limit=limit,
        symbol=symbol,
    )
    
    return {
        "status": "ok",
        "total": len(history),
        "history": history,
    }


@router.delete("/history/{record_id}", summary="删除单条评估记录")
async def delete_evaluation_record(
    record_id: int,
    account_id: Optional[str] = Query(None, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """删除指定的评估记录"""
    svc = AITradeAdvisorService(session)
    acc_id = account_id or settings.TIGER_ACCOUNT
    
    success = await svc.delete_evaluation_record(record_id, acc_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=t("error.delete_denied"))
    
    return {"status": "ok", "message": "Record deleted"}


# ==================== 辅助函数 ====================

def _plan_to_dict(plan) -> dict:
    """将 ORM 对象转为字典"""
    return {
        "id": plan.id,
        "symbol": plan.symbol,
        "entry_price": float(plan.entry_price) if plan.entry_price else 0,
        "stop_loss": float(plan.stop_loss) if plan.stop_loss else 0,
        "take_profit": float(plan.take_profit) if plan.take_profit else 0,
        "target_position": float(plan.target_position) if plan.target_position else 0,
        "plan_status": plan.plan_status or "ACTIVE",
        "notes": plan.notes or "",
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
