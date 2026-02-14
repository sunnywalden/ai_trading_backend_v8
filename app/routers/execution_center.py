"""执行中心 API - Layer 3 集中管理所有待执行的交易计划"""
from typing import Optional, List, Callable
from fastapi import APIRouter, Depends, HTTPException, Query
from app.i18n import get_translator
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.models.db import get_session
from app.services.trading_plan_service import TradingPlanService
from app.core.config import settings


router = APIRouter(prefix="/api/v1/execution-center", tags=["Execution Center"])


# ==================== 请求/响应模型 ====================

class TradingPlanCreate(BaseModel):
    """创建交易计划请求"""
    symbol: str = Field(..., description="交易标的")
    entry_price: float = Field(..., gt=0, description="入场价格")
    stop_loss: float = Field(..., gt=0, description="止损价格")
    take_profit: float = Field(..., gt=0, description="止盈价格")
    target_position: float = Field(..., gt=0, le=1, description="目标仓位比例")
    valid_from: Optional[str] = Field(None, description="生效开始时间")
    valid_until: Optional[str] = Field(None, description="生效结束时间")
    notes: Optional[str] = Field(None, description="备注")
    plan_tags: Optional[dict] = Field(None, description="计划标签")


class TradingPlanUpdate(BaseModel):
    """更新交易计划请求"""
    entry_price: Optional[float] = Field(None, gt=0)
    stop_loss: Optional[float] = Field(None, gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    target_position: Optional[float] = Field(None, gt=0, le=1)
    plan_status: Optional[str] = Field(None, description="ACTIVE/PAUSED/EXECUTED/CANCELLED/FAILED")
    notes: Optional[str] = None


class ExecutePlanRequest(BaseModel):
    """执行计划请求"""
    plan_ids: List[int] = Field(..., description="要执行的计划ID列表", min_items=1)


class CancelPlanRequest(BaseModel):
    """取消计划请求"""
    plan_ids: List[int] = Field(..., description="要取消的计划ID列表", min_items=1)
    reason: Optional[str] = Field(None, description="取消原因")


class TradingPlanResponse(BaseModel):
    """交易计划响应"""
    id: int
    account_id: str
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    target_position: float
    plan_status: str
    plan_tags: Optional[dict]
    valid_from: Optional[str]
    valid_until: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class PaginatedPlansResponse(BaseModel):
    """分页计划列表响应"""
    total: int
    page: int
    page_size: int
    total_pages: int
    plans: List[TradingPlanResponse]


# ==================== API 端点 ====================

@router.get("/plans", response_model=PaginatedPlansResponse, summary="获取交易计划列表")
async def get_plans(
    status: Optional[str] = Query(None, description="计划状态: ACTIVE/PAUSED/EXECUTED/CANCELLED/FAILED"),
    symbol: Optional[str] = Query(None, description="标的代码"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取交易计划列表（分页）
    
    - 支持按状态筛选
    - 支持按标的筛选
    - 默认按创建时间倒序
    """
    service = TradingPlanService(session)
    account_id = settings.TIGER_ACCOUNT  # 从配置获取账户ID
    
    plans, total = await service.get_plans_with_pagination(
        account_id=account_id,
        status=status,
        symbol=symbol,
        page=page,
        page_size=page_size
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "plans": plans
    }


@router.get("/plans/{plan_id}", response_model=TradingPlanResponse, summary="获取计划详情")
async def get_plan_detail(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """获取单个交易计划的详细信息"""
    service = TradingPlanService(session)
    plan = await service.get_plan_by_id(plan_id)
    
    if not plan:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    
    return plan


@router.post("/plans", response_model=TradingPlanResponse, summary="创建交易计划")
async def create_plan(
    request: TradingPlanCreate,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """
    创建新的交易计划
    
    - 自动验证价格关系（止损 < 入场价 < 止盈）
    - 验证目标仓位在合理范围内
    """
    service = TradingPlanService(session)
    account_id = settings.TIGER_ACCOUNT
    
    try:
        plan = await service.create_plan(
            account_id=account_id,
            payload=request.dict(exclude_none=True)
        )
        return plan
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/plans/{plan_id}", response_model=TradingPlanResponse, summary="更新交易计划")
async def update_plan(
    plan_id: int,
    request: TradingPlanUpdate,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """更新交易计划参数"""
    service = TradingPlanService(session)
    
    plan = await service.update_plan(
        plan_id=plan_id,
        payload=request.dict(exclude_none=True)
    )
    
    if not plan:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    
    return plan


@router.delete("/plans/{plan_id}", summary="删除交易计划")
async def delete_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """彻底删除交易计划"""
    service = TradingPlanService(session)
    success = await service.delete_plan(plan_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=t("error.plan_not_found", id=plan_id))
    
    return {"success": True, "message": f"Plan {plan_id} deleted"}


@router.post("/execute", summary="执行交易计划")
async def execute_plans(
    request: ExecutePlanRequest,
    session: AsyncSession = Depends(get_session),
    t: Callable = Depends(get_translator)
):
    """
    执行一个或多个交易计划
    
    - 支持单个执行
    - 支持批量执行
    - 返回每个计划的执行结果
    """
    service = TradingPlanService(session)
    
    if len(request.plan_ids) == 1:
        # 单个执行
        try:
            result = await service.execute_plan(request.plan_ids[0])
            return {
                "success": result["success"],
                "results": [result]
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        # 批量执行
        results = await service.batch_execute_plans(request.plan_ids)
        return {
            "success": results["success_count"] > 0,
            "total": results["total"],
            "success_count": results["success_count"],
            "failed_count": results["failed_count"],
            "results": results["details"]
        }


@router.post("/cancel", summary="取消交易计划")
async def cancel_plans(
    request: CancelPlanRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    取消一个或多个交易计划
    
    - 计划状态变更为 CANCELLED
    - 可选提供取消原因
    """
    service = TradingPlanService(session)
    
    cancelled_count = await service.batch_cancel_plans(
        plan_ids=request.plan_ids,
        reason=request.reason
    )
    
    return {
        "success": cancelled_count > 0,
        "cancelled_count": cancelled_count,
        "total": len(request.plan_ids),
        "message": f"成功取消 {cancelled_count} 个计划"
    }


@router.get("/stats", summary="获取执行中心统计")
async def get_execution_stats(
    session: AsyncSession = Depends(get_session)
):
    """
    获取执行中心统计数据
    
    - 各状态的计划数量
    - 今日执行数量
    - 成功率等
    """
    service = TradingPlanService(session)
    account_id = settings.TIGER_ACCOUNT
    
    # 获取各状态的计划
    all_plans = await service.list_plans(account_id=account_id)
    
    stats = {
        "total": len(all_plans),
        "active": len([p for p in all_plans if p.plan_status == "ACTIVE"]),
        "paused": len([p for p in all_plans if p.plan_status == "PAUSED"]),
        "executed": len([p for p in all_plans if p.plan_status == "EXECUTED"]),
        "cancelled": len([p for p in all_plans if p.plan_status == "CANCELLED"]),
        "failed": len([p for p in all_plans if p.plan_status == "FAILED"])
    }
    
    return stats
