"""
量化交易闭环API路由

提供完整的监控、控制和报表接口
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.models.db import get_session
from app.engine.quant_trading_loop import QuantTradingLoop
from app.engine.signal_engine import SignalEngine
from app.engine.order_executor import OrderExecutor
from app.engine.performance_analyzer import PerformanceAnalyzer
from app.engine.adaptive_optimizer import AdaptiveOptimizer
from app.core.auth import get_current_user
from app.core.config import settings


# Request/Response Models
class ExecuteSignalsRequest(BaseModel):
    signal_ids: List[str]
    dry_run: bool = True


class RejectSignalsRequest(BaseModel):
    signal_ids: List[str]
    reason: Optional[str] = None


router = APIRouter(prefix="/api/v1/quant-loop", tags=["Quantitative Trading Loop"])


@router.post("/run-cycle")
async def run_full_cycle(
    account_id: Optional[str] = None,
    execute_trades: bool = False,
    optimize: bool = True,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    运行完整的量化交易闭环周期
    
    - **execute_trades**: 是否执行实际交易(默认False为安全)
    - **optimize**: 是否运行优化(默认True)
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    loop = QuantTradingLoop(session)
    
    try:
        results = await loop.run_full_cycle(
            account_id=account_id,
            execute_trades=execute_trades,
            optimize=optimize
        )
        return {
            "success": True,
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cycle execution failed: {str(e)}")


@router.get("/status")
async def get_loop_status(
    account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取闭环系统状态"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    loop = QuantTradingLoop(session)
    status = await loop.get_loop_status(account_id)
    
    return {
        "success": True,
        "data": status
    }


@router.get("/signals/pending")
async def get_pending_signals(
    account_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    filter_by_position: bool = Query(False, description="是否根据持仓过滤信号"),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取待执行的信号列表（支持持仓过滤）"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    # 如果配置中也没有，尝试从 broker 获取默认账户 ID
    if not account_id:
        try:
            from app.broker.factory import make_option_broker_client
            broker = make_option_broker_client()
            account_id = await broker.get_account_id()
        except Exception:
            pass
            
    signal_engine = SignalEngine(session)
    signals = await signal_engine.get_pending_signals(
        account_id=account_id,
        limit=limit
    )
    
    filter_stats = None
    
    # 🔍 根据持仓过滤信号
    if filter_by_position and signals:
        try:
            # 这里的 account_id 必须是有效的，用于查询该账户的真实持仓
            if not account_id:
                 # 保底层：如果没有 account_id，尝试获取一次
                 from app.broker.factory import make_option_broker_client
                 broker = make_option_broker_client()
                 account_id = await broker.get_account_id()

            from app.engine.signal_position_filter import SignalPositionFilter
            signal_filter = SignalPositionFilter(session)
            signals, filter_stats = await signal_filter.filter_signals_with_positions(
                signals, 
                account_id
            )
        except Exception as e:
            import traceback
            print(f"信号过滤失败: {e}")
            traceback.print_exc()
            # 过滤失败不影响返回，继续返回未过滤的信号
    
    return {
        "success": True,
        "data": [
            {
                "signal_id": s.signal_id,
                "symbol": s.symbol,
                "signal_type": s.signal_type.value,
                "signal_source": s.signal_source.value,
                "signal_strength": s.signal_strength,
                "confidence": s.confidence,
                "direction": s.direction,
                "suggested_quantity": s.suggested_quantity,
                "suggested_price": s.suggested_price,
                "expected_return": s.expected_return,
                "risk_score": s.risk_score,
                "priority": s.priority,
                "generated_at": s.generated_at.isoformat(),
                "expired_at": s.expired_at.isoformat() if s.expired_at else None,
                "extra_metadata": s.extra_metadata  # 包含持仓信息和过滤原因
            }
            for s in signals
        ],
        "total": len(signals),
        "filter_stats": filter_stats  # 过滤统计信息
    }


@router.post("/signals/{signal_id}/validate")
async def validate_signal(
    signal_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """手动验证单个信号"""
    signal_engine = SignalEngine(session)
    
    is_valid = await signal_engine.validate_signal(signal_id)
    
    return {
        "success": True,
        "data": {
            "signal_id": signal_id,
            "validated": is_valid
        }
    }


@router.get("/signals/{signal_id}/summary")
async def get_signal_summary(
    signal_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取交易信号的AI生成摘要"""
    from sqlalchemy import select
    from app.models.trading_signal import TradingSignal
    from app.services.ai_analysis_service import AIAnalysisService
    
    stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
    result = await session.execute(stmt)
    signal = result.scalars().first()
    
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    ai_service = AIAnalysisService()
    
    # 构建输入数据
    signal_data = {
        "symbol": signal.symbol,
        "direction": signal.direction,
        "signal_type": signal.signal_type.value if hasattr(signal.signal_type, 'value') else signal.signal_type,
        "signal_strength": signal.signal_strength,
        "confidence": signal.confidence,
        "factor_scores": signal.factor_scores,
        "extra_metadata": signal.extra_metadata
    }
    
    summary = await ai_service.generate_signal_summary(signal_data)
    
    return {
        "success": True,
        "summary": summary
    }


@router.post("/signals/{signal_id}/cancel")
async def cancel_signal(
    signal_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """取消信号"""
    executor = OrderExecutor(session)
    
    cancelled = await executor.cancel_signal(signal_id)
    
    return {
        "success": True,
        "data": {
            "signal_id": signal_id,
            "cancelled": cancelled
        }
    }


@router.post("/execute-signals")
async def execute_signals_batch(
    request: ExecuteSignalsRequest,
    account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    批量执行指定的信号
    
    - **signal_ids**: 要执行的信号ID列表
    - **dry_run**: 演练模式(默认True)
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    if not request.signal_ids:
        raise HTTPException(status_code=400, detail="signal_ids不能为空")
    
    executor = OrderExecutor(session)
    signal_engine = SignalEngine(session)
    
    from app.core.trade_mode import TradeMode
    from app.models.trading_signal import SignalStatus
    trade_mode = TradeMode.DRY_RUN if request.dry_run else TradeMode.REAL
    
    # 获取指定的信号
    from sqlalchemy import select
    from app.models.trading_signal import TradingSignal
    
    stmt = select(TradingSignal).where(
        TradingSignal.signal_id.in_(request.signal_ids)
    )
    result = await session.execute(stmt)
    signals = list(result.scalars().all())
    
    if not signals:
        return {
            "success": True,
            "data": {
                "success_count": 0,
                "failed_count": 0,
                "message": "未找到指定的信号"
            }
        }
    
    # 获取账户信息
    account_equity = await executor.account_svc.get_equity_usd(account_id)
    
    success_count = 0
    failed_count = 0
    execution_results = []
    
    for signal in signals:
        try:
            # 检查信号是否可执行
            if signal.status not in [SignalStatus.VALIDATED, SignalStatus.QUEUED]:
                failed_count += 1
                execution_results.append({
                    "signal_id": signal.signal_id,
                    "success": False,
                    "message": f"信号状态不正确: {signal.status.value}"
                })
                continue
            
            # 更新信号状态为执行中
            signal.status = SignalStatus.EXECUTING
            await session.commit()
            
            # 执行订单
            result = await executor._execute_single_signal(
                signal=signal,
                account_equity=account_equity,
                trade_mode=trade_mode
            )
            
            execution_results.append({
                "signal_id": signal.signal_id,
                "success": result["success"],
                "message": result.get("message", ""),
                "order_id": result.get("order_id")
            })
            
            if result["success"]:
                success_count += 1
                # 标记为已执行
                signal.status = SignalStatus.EXECUTED
            else:
                failed_count += 1
                # 保持 VALIDATED 状态，以便在待执行列表中保留
                signal.status = SignalStatus.VALIDATED
                
            await session.commit()
                
        except Exception as e:
            failed_count += 1
            # 保持 VALIDATED 状态，以便在待执行列表中保留
            signal.status = SignalStatus.VALIDATED
            await session.commit()
            
            execution_results.append({
                "signal_id": signal.signal_id,
                "success": False,
                "message": str(e)
            })
    
    return {
        "success": True,
        "data": {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": execution_results
        }
    }


@router.post("/reject-signals")
async def reject_signals_batch(
    request: RejectSignalsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    批量拒绝指定的信号
    
    - **signal_ids**: 要拒绝的信号ID列表
    - **reason**: 拒绝原因（可选）
    """
    if not request.signal_ids:
        raise HTTPException(status_code=400, detail="signal_ids不能为空")
    
    from sqlalchemy import select
    from app.models.trading_signal import TradingSignal, SignalStatus
    
    # 获取指定的信号
    stmt = select(TradingSignal).where(
        TradingSignal.signal_id.in_(request.signal_ids)
    )
    result = await session.execute(stmt)
    signals = list(result.scalars().all())
    
    if not signals:
        return {
            "success": True,
            "data": {
                "rejected_count": 0,
                "failed_count": 0,
                "message": "未找到指定的信号"
            }
        }
    
    rejected_count = 0
    failed_count = 0
    rejection_results = []
    
    for signal in signals:
        try:
            # 检查信号是否可拒绝（只能拒绝GENERATED或VALIDATED状态的信号）
            if signal.status not in [SignalStatus.GENERATED, SignalStatus.VALIDATED]:
                failed_count += 1
                rejection_results.append({
                    "signal_id": signal.signal_id,
                    "success": False,
                    "message": f"信号状态不正确: {signal.status.value}，只能拒绝GENERATED或VALIDATED状态的信号"
                })
                continue
            
            # 更新信号状态为已拒绝
            signal.status = SignalStatus.REJECTED
            
            # 如果提供了拒绝原因，记录到extra_metadata
            if request.reason:
                if not signal.extra_metadata:
                    signal.extra_metadata = {}
                signal.extra_metadata["rejection_reason"] = request.reason
                signal.extra_metadata["rejected_at"] = datetime.utcnow().isoformat()
                signal.extra_metadata["rejected_by"] = current_user.get("username", "unknown")
            
            await session.commit()
            rejected_count += 1
            
            rejection_results.append({
                "signal_id": signal.signal_id,
                "success": True,
                "message": "已拒绝"
            })
                
        except Exception as e:
            failed_count += 1
            rejection_results.append({
                "signal_id": signal.signal_id,
                "success": False,
                "message": str(e)
            })
    
    return {
        "success": True,
        "data": {
            "rejected_count": rejected_count,
            "failed_count": failed_count,
            "results": rejection_results
        }
    }


@router.get("/performance/daily")
async def get_daily_performance(
    account_id: Optional[str] = None,
    date: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取每日性能报告"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    target_date = datetime.fromisoformat(date) if date else datetime.utcnow()
    
    analyzer = PerformanceAnalyzer(session)
    performance = await analyzer.evaluate_daily_performance(
        account_id=account_id,
        target_date=target_date
    )
    
    return {
        "success": True,
        "data": performance
    }


@router.get("/performance/strategy/{strategy_id}")
async def get_strategy_performance(
    strategy_id: str,
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取策略性能报告"""
    analyzer = PerformanceAnalyzer(session)
    report = await analyzer.generate_strategy_report(
        strategy_id=strategy_id,
        days=days
    )
    
    return {
        "success": True,
        "data": report
    }


@router.get("/optimization/opportunities")
async def get_improvement_opportunities(
    account_id: Optional[str] = None,
    days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """获取改进机会分析"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    analyzer = PerformanceAnalyzer(session)
    opportunities = await analyzer.identify_improvement_opportunities(
        account_id=account_id,
        days=days
    )
    
    return {
        "success": True,
        "data": opportunities
    }


@router.post("/optimization/run")
async def run_optimization(
    account_id: Optional[str] = None,
    auto_apply: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    运行系统优化
    
    - **auto_apply**: 是否自动应用优化结果(默认False,需人工审核)
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    optimizer = AdaptiveOptimizer(session)
    results = await optimizer.run_daily_optimization(account_id)
    
    return {
        "success": True,
        "data": results,
        "message": "Optimization completed. Review results before applying." if not auto_apply else "Optimization applied automatically."
    }


@router.post("/strategy/{strategy_id}/research-cycle")
async def run_strategy_research_cycle(
    strategy_id: str,
    account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """运行单个策略的研究→交易周期"""
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    loop = QuantTradingLoop(session)
    results = await loop.run_strategy_research_cycle(
        account_id=account_id,
        strategy_id=strategy_id
    )
    
    return {
        "success": True,
        "data": results
    }


@router.get("/dashboard/overview")
async def get_dashboard_overview(
    account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    获取闭环系统仪表盘概览
    用于监控整个系统的运行状态
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    loop = QuantTradingLoop(session)
    signal_engine = SignalEngine(session)
    
    # 系统状态
    status = await loop.get_loop_status(account_id)
    
    # 待执行信号
    from app.models.trading_signal import SignalStatus
    pending_signals = await signal_engine.get_pending_signals(
        account_id=account_id,
        status=SignalStatus.VALIDATED,
        limit=5
    )
    
    # 最近执行的信号
    recent_executed = await signal_engine.get_pending_signals(
        account_id=account_id,
        status=SignalStatus.EXECUTED,
        limit=10
    )
    
    return {
        "success": True,
        "data": {
            "system_status": status,
            "pending_signals_count": len(pending_signals),
            "recent_executed_count": len(recent_executed),
            "top_pending_signals": [
                {
                    "symbol": s.symbol,
                    "signal_strength": s.signal_strength,
                    "confidence": s.confidence,
                    "expected_return": s.expected_return,
                }
                for s in pending_signals[:3]
            ],
            "last_update": datetime.utcnow().isoformat()
        }
    }


@router.post("/sync-executing-orders")
async def sync_executing_orders(
    account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user)
):
    """
    同步所有执行中订单的状态
    
    定期调用此接口以检测券商侧的订单变化（如因资金不足被撤销）
    建议前端在"待执行信号"页面每30秒自动调用一次
    """
    if not account_id:
        account_id = settings.TIGER_ACCOUNT
    
    from app.engine.order_executor import OrderExecutor
    executor = OrderExecutor(session)
    
    try:
        result = await executor.sync_executing_orders(account_id)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
