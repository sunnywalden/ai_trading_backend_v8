"""
Alpha/Beta 性能分析 API 路由

提供Alpha、Beta、Sharpe等高级性能指标的API接口
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.core.auth import get_current_user
from app.engine.performance_analyzer import PerformanceAnalyzer
from app.services.var_calculator import VaRCalculator
from app.services.smart_order_router import SmartOrderRouter, OrderUrgency


router = APIRouter(prefix="/api/v1/performance", tags=["Performance Analytics"])


@router.get("/alpha-beta/{account_id}")
async def get_alpha_beta_metrics(
    account_id: str,
    period_days: int = Query(default=90, ge=30, le=365, description="分析周期（天）"),
    benchmark: str = Query(default="SPY", description="基准指数（SPY/QQQ/IWM)"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    获取Alpha/Beta性能指标
    
    - **Alpha**: 超额收益（相对基准）
    - **Beta**: 系统性风险暴露
    - **Sharpe Ratio**: 夏普比率
    - **Information Ratio**: 信息比率
    - **Sortino Ratio**: 索提诺比率
    - **Calmar Ratio**: 卡玛比率
    
    **示例响应**:
    ```json
    {
      "alpha": 0.08,
      "beta": 0.85,
      "sharpe_ratio": 1.65,
      "information_ratio": 0.45,
      "sortino_ratio": 2.1,
      "calmar_ratio": 1.2,
      "benchmark": "SPY",
      "period_days": 90,
      "interpretation": "您的策略Alpha为8%，表现优于基准..."
    }
    ```
    """
    analyzer = PerformanceAnalyzer(session)
    
    try:
        metrics = await analyzer.calculate_alpha_beta_metrics(
            account_id=account_id,
            period_days=period_days,
            benchmark_symbol=benchmark
        )
        
        if "error" in metrics:
            raise HTTPException(status_code=400, detail=metrics["error"])
        
        return {"success": True, "data": metrics}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算Alpha/Beta失败: {str(e)}")


@router.get("/signal-quality/{account_id}")
async def get_signal_quality_metrics(
    account_id: str,
    period_days: int = Query(default=30, ge=7, le=180, description="分析周期（天）"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    获取信号质量指标
    
    - **Win Rate**: 胜率
    - **Avg Win/Loss**: 平均盈亏
    - **Profit Factor**: 盈亏比
    - **Best/Worst Signal**: 最佳/最差信号
    
    **按策略、信号源分组**
    
    **示例响应**:
    ```json
    {
      "overall_win_rate": 0.58,
      "total_signals": 45,
      "winning_signals": 26,
      "by_strategy": {
        "momentum_v2": {"win_rate": 0.62, "count": 20},
        "mean_reversion_v1": {"win_rate": 0.55, "count": 25}
      },
      "by_source": {
        "deepseek": {"win_rate": 0.60, "count": 30},
        "technical_analysis": {"win_rate": 0.53, "count": 15}
      }
    }
    ```
    """
    analyzer = PerformanceAnalyzer(session)
    
    try:
        quality_metrics = await analyzer.calculate_signal_win_rate(
            account_id=account_id,
            period_days=period_days
        )
        
        if "error" in quality_metrics:
            raise HTTPException(status_code=400, detail=quality_metrics["error"])
        
        return {"success": True, "data": quality_metrics}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算信号质量失败: {str(e)}")


@router.get("/var-risk/{account_id}")
async def get_var_risk_metrics(
    account_id: str,
    confidence_level: float = Query(default=0.95, ge=0.90, le=0.99, description="置信度"),
    days: int = Query(default=252, ge=60, le=504, description="历史数据天数"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    获取VaR/CVaR风险指标
    
    - **VaR (Value at Risk)**: 在险价值
    - **CVaR (Conditional VaR)**: 条件在险价值/期望损失
    - **Max Drawdown**: 最大回撤
    - **Volatility**: 波动率
    
    **示例响应**:
    ```json
    {
      "var_95_pct": -0.018,
      "var_95_dollar": -2300,
      "cvar_95_pct": -0.025,
      "cvar_95_dollar": -3200,
      "max_drawdown_pct": -0.12,
      "volatility_annualized": 0.22,
      "risk_level": "MEDIUM",
      "interpretation": "在95%置信度下，您的投资组合..."
    }
    ```
    """
    calculator = VaRCalculator(session)
    
    try:
        var_metrics = await calculator.calculate_var_cvar(
            account_id=account_id,
            confidence_level=confidence_level,
            days=days
        )
        
        if "error" in var_metrics:
            raise HTTPException(status_code=400, detail=var_metrics["error"])
        
        return {"success": True, "data": var_metrics}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算VaR失败: {str(e)}")


@router.get("/stress-test/{account_id}")
async def run_stress_test(
    account_id: str,
    scenario: str = Query(default="2008_crisis", description="压力情景（2008_crisis/2020_covid/black_monday）"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    运行压力测试
    
    模拟极端市场情景下的组合表现：
    - **2008_crisis**: 2008年金融危机（-37%）
    - **2020_covid**: 2020年疫情暴跌（-34%）
    - **black_monday**: 黑色星期一（-20%单日）
    
    **示例响应**:
    ```json
    {
      "scenario_name": "2008年金融危机",
      "market_scenario": -0.37,
      "estimated_loss_pct": -0.28,
      "estimated_loss_dollar": -35000,
      "stress_var": -0.84,
      "recommendation": "压力情景下损失较大，建议..."
    }
    ```
    """
    calculator = VaRCalculator(session)
    
    try:
        stress_result = await calculator.stress_test(
            account_id=account_id,
            scenario=scenario
        )
        
        return {"success": True, "data": stress_result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"压力测试失败: {str(e)}")


@router.post("/smart-order-routing")
async def route_smart_order(
    symbol: str = Query(..., description="股票代码"),
    quantity: int = Query(..., ge=1, description="数量"),
    side: str = Query(..., regex="^(BUY|SELL)$", description="买入/卖出"),
    urgency: str = Query(default="NORMAL", regex="^(LOW|NORMAL|HIGH)$", description="紧急度"),
    account_id: Optional[str] = Query(None, description="账户ID"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    智能订单路由
    
    根据订单大小、市场流动性、波动率自动选择最优执行策略：
    - 小单 → 市价单
    - 中单 → 限价单
    - 大单 → TWAP/VWAP算法交易
    
    **示例请求**:
    ```
    POST /api/performance/smart-order-routing?symbol=AAPL&quantity=5000&side=BUY&urgency=NORMAL
    ```
    
    **示例响应**:
    ```json
    {
      "order_type": "LMT",
      "limit_price": 150.25,
      "quantity": 5000,
      "algo_strategy": "TWAP",
      "execution_horizon": "4hours",
      "slippage_estimate": 0.0015,
      "reasoning": "较大订单（占ADV 3.5%），使用TWAP分批执行"
    }
    ```
    """
    router_service = SmartOrderRouter(session)
    
    try:
        # 转换紧急度枚举
        urgency_enum = OrderUrgency(urgency)
        
        routing_result = await router_service.route_order(
            symbol=symbol,
            quantity=quantity,
            side=side,
            urgency=urgency_enum,
            account_id=account_id
        )
        
        return {"success": True, "data": routing_result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"订单路由失败: {str(e)}")


@router.post("/evaluate-execution")
async def evaluate_execution_quality(
    symbol: str = Query(..., description="股票代码"),
    executed_price: float = Query(..., gt=0, description="成交价格"),
    quantity: int = Query(..., ge=1, description="成交数量"),
    side: str = Query(..., regex="^(BUY|SELL)$", description="买入/卖出"),
    execution_time: Optional[datetime] = Query(None, description="成交时间"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    评估订单执行质量
    
    事后分析执行质量，计算实际滑点、相对VWAP的差异
    
    **示例响应**:
    ```json
    {
      "execution_quality": "GOOD",
      "score": 85,
      "slippage_actual": 0.0012,
      "price_improvement": -0.0005,
      "interpretation": "执行质量良好，实际滑点0.12%"
    }
    ```
    """
    router_service = SmartOrderRouter(session)
    
    try:
        if execution_time is None:
            execution_time = datetime.utcnow()
        
        eval_result = await router_service.evaluate_execution_quality(
            symbol=symbol,
            executed_price=executed_price,
            quantity=quantity,
            side=side,
            execution_time=execution_time
        )
        
        if "error" in eval_result:
            raise HTTPException(status_code=400, detail=eval_result["error"])
        
        return {"success": True, "data": eval_result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行质量评估失败: {str(e)}")


@router.get("/dashboard/{account_id}")
async def get_performance_dashboard(
    account_id: str,
    period_days: int = Query(default=90, ge=30, le=365, description="分析周期（天）"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user)
):
    """
    获取完整性能仪表板数据
    
    一次性返回所有核心指标，适用于前端仪表板展示
    
    **包含**:
    - Alpha/Beta指标
    - 信号质量指标
    - VaR风险指标
    - 账户概览
    
    **示例响应**:
    ```json
    {
      "alpha_beta": {...},
      "signal_quality": {...},
      "var_risk": {...},
      "account_summary": {
        "total_equity": 125000,
        "total_return": 0.25,
        "sharpe_ratio": 1.65
      }
    }
    ```
    """
    analyzer = PerformanceAnalyzer(session)
    var_calculator = VaRCalculator(session)
    
    try:
        # 并行获取所有指标
        import asyncio
        
        alpha_beta_task = analyzer.calculate_alpha_beta_metrics(
            account_id=account_id,
            period_days=period_days
        )
        
        signal_quality_task = analyzer.calculate_signal_win_rate(
            account_id=account_id,
            period_days=min(period_days, 90)  # 信号质量用较短周期
        )
        
        var_risk_task = var_calculator.calculate_var_cvar(
            account_id=account_id,
            confidence_level=0.95,
            days=min(period_days, 252)
        )
        
        alpha_beta, signal_quality, var_risk = await asyncio.gather(
            alpha_beta_task,
            signal_quality_task,
            var_risk_task,
            return_exceptions=True
        )
        
        # 处理异常
        dashboard = {
            "account_id": account_id,
            "period_days": period_days,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if not isinstance(alpha_beta, Exception):
            dashboard["alpha_beta"] = alpha_beta
        else:
            dashboard["alpha_beta"] = {"error": str(alpha_beta)}
        
        if not isinstance(signal_quality, Exception):
            dashboard["signal_quality"] = signal_quality
        else:
            dashboard["signal_quality"] = {"error": str(signal_quality)}
        
        if not isinstance(var_risk, Exception):
            dashboard["var_risk"] = var_risk
        else:
            dashboard["var_risk"] = {"error": str(var_risk)}
        
        return {"success": True, "data": dashboard}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取仪表板数据失败: {str(e)}")
