# 模块7: API端点实现设计

## 1. 端点概览

### 1.1 持仓评估相关API (4个)
1. `GET /api/v1/positions/assessment` - 获取所有持仓的综合评估
2. `GET /api/v1/positions/{symbol}/technical` - 获取单个标的技术分析
3. `GET /api/v1/positions/{symbol}/fundamental` - 获取单个标的基本面分析
4. `POST /api/v1/positions/refresh` - 刷新持仓评分

### 1.2 宏观风险相关API (4个)
5. `GET /api/v1/macro/risk/overview` - 获取宏观风险总览
6. `GET /api/v1/macro/monetary-policy` - 获取货币政策分析
7. `GET /api/v1/macro/geopolitical-events` - 获取地缘政治事件
8. `POST /api/v1/macro/refresh` - 刷新宏观数据

---

## 2. 端点详细设计

### 2.1 获取持仓评估

```python
# app/routers/position_macro.py

@router.get(
    "/positions/assessment",
    response_model=PositionsAssessmentResponse,
    summary="获取持仓综合评估",
    description="获取所有持仓的技术面、基本面、情绪面评分和投资建议"
)
async def get_positions_assessment(
    window_days: int = Query(7, ge=1, le=90, description="统计窗口（天）"),
    use_cache: bool = Query(True, description="是否使用缓存"),
    session: AsyncSession = Depends(get_session),
    account_id: str = Depends(get_current_account_id)
):
    """
    获取持仓综合评估
    
    流程:
    1. 从Tiger API获取当前持仓列表
    2. 批量计算每个标的的评分（技术+基本面+情绪）
    3. 生成投资建议和风险预警
    4. 计算组合统计（平均分、高风险标的数等）
    5. 返回完整评估报告
    
    参数:
    - window_days: 数据统计窗口，默认7天
    - use_cache: 是否使用缓存数据，默认True
    
    返回:
    - PositionsAssessmentResponse: 包含所有持仓评估和组合摘要
    
    错误码:
    - 400: 参数错误
    - 401: 未授权
    - 500: 服务器错误
    """
    
    try:
        # 1. 获取持仓列表
        from app.services.account_service import AccountService
        account_service = AccountService(session, account_id)
        positions = await account_service.get_current_positions()
        
        if not positions:
            return PositionsAssessmentResponse(
                positions=[],
                portfolio_summary=PortfolioSummaryDTO(
                    total_positions=0,
                    average_score=0,
                    high_risk_count=0,
                    recommended_actions={}
                ),
                last_updated=datetime.utcnow()
            )
        
        # 2. 批量计算评分
        from app.services.position_scoring_service import PositionScoringService
        scoring_service = PositionScoringService(session, account_id)
        
        position_data = [
            {
                "symbol": p.symbol,
                "current_price": p.market_value / p.quantity,
                "position_size": p.market_value
            }
            for p in positions
        ]
        
        scores = await scoring_service.batch_calculate_scores(position_data)
        
        # 3. 构建响应
        high_risk_count = sum(1 for s in scores if s.risk_level in ["HIGH", "EXTREME"])
        average_score = sum(s.overall_score for s in scores) / len(scores)
        
        # 统计建议动作
        recommended_actions = {}
        for score in scores:
            action = score.recommendation.action
            recommended_actions[action] = recommended_actions.get(action, 0) + 1
        
        return PositionsAssessmentResponse(
            positions=scores,
            portfolio_summary=PortfolioSummaryDTO(
                total_positions=len(positions),
                average_score=round(average_score, 2),
                high_risk_count=high_risk_count,
                recommended_actions=recommended_actions
            ),
            last_updated=datetime.utcnow()
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get positions assessment: {e}")
        raise HTTPException(status_code=500, detail="获取持仓评估失败")
```

---

### 2.2 获取技术分析

```python
@router.get(
    "/positions/{symbol}/technical",
    response_model=TechnicalAnalysisDTO,
    summary="获取技术分析",
    description="获取指定标的的技术指标和分析"
)
async def get_technical_analysis(
    symbol: str = Path(..., description="股票代码，如AAPL"),
    timeframe: str = Query("1D", regex="^(1D|1W|1M)$", description="时间周期"),
    use_cache: bool = Query(True, description="是否使用缓存"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取技术分析
    
    流程:
    1. 验证symbol格式
    2. 调用TechnicalAnalysisService获取分析
    3. 返回技术指标和AI摘要
    
    参数:
    - symbol: 股票代码（必填）
    - timeframe: K线周期，支持1D/1W/1M
    - use_cache: 是否使用缓存
    
    返回:
    - TechnicalAnalysisDTO: 技术分析结果
    
    错误码:
    - 400: 无效的symbol
    - 404: 标的不存在
    - 500: 分析失败
    """
    
    try:
        # 验证symbol
        if not symbol or len(symbol) > 10:
            raise HTTPException(status_code=400, detail="无效的股票代码")
        
        # 调用服务
        from app.services.technical_analysis_service import TechnicalAnalysisService
        tech_service = TechnicalAnalysisService(session)
        
        result = await tech_service.get_technical_analysis(
            symbol=symbol.upper(),
            timeframe=timeframe,
            use_cache=use_cache
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"标的{symbol}不存在或数据不足")
    except Exception as e:
        logger.error(f"Technical analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="技术分析失败")
```

---

### 2.3 获取基本面分析

```python
@router.get(
    "/positions/{symbol}/fundamental",
    response_model=FundamentalAnalysisDTO,
    summary="获取基本面分析",
    description="获取指定标的的财务数据和估值分析"
)
async def get_fundamental_analysis(
    symbol: str = Path(..., description="股票代码"),
    use_cache: bool = Query(True, description="是否使用缓存"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取基本面分析
    
    流程:
    1. 调用FundamentalAnalysisService
    2. 返回估值、盈利、成长、健康度指标
    
    参数:
    - symbol: 股票代码
    - use_cache: 是否使用缓存（基本面数据每天更新一次）
    
    返回:
    - FundamentalAnalysisDTO: 基本面分析结果
    
    错误码:
    - 400: 无效的symbol
    - 404: 标的不存在或无财务数据
    - 500: 分析失败
    """
    
    try:
        from app.services.fundamental_analysis_service import FundamentalAnalysisService
        fundamental_service = FundamentalAnalysisService(session)
        
        result = await fundamental_service.get_fundamental_analysis(
            symbol=symbol.upper(),
            use_cache=use_cache
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"无法获取{symbol}的基本面数据")
    except Exception as e:
        logger.error(f"Fundamental analysis failed for {symbol}: {e}")
        raise HTTPException(status_code=500, detail="基本面分析失败")
```

---

### 2.4 刷新持仓评分

```python
@router.post(
    "/positions/refresh",
    response_model=Dict[str, Any],
    summary="刷新持仓评分",
    description="强制刷新所有持仓的评分数据"
)
async def refresh_positions(
    symbols: Optional[List[str]] = Body(None, description="要刷新的标的列表，不传则刷新全部"),
    session: AsyncSession = Depends(get_session),
    account_id: str = Depends(get_current_account_id)
):
    """
    刷新持仓评分
    
    流程:
    1. 获取待刷新的标的列表
    2. 并发刷新技术面和基本面数据
    3. 重新计算评分
    4. 返回刷新结果统计
    
    参数:
    - symbols: 可选，指定要刷新的标的列表
    
    返回:
    - 刷新结果统计
    
    错误码:
    - 401: 未授权
    - 500: 刷新失败
    """
    
    try:
        from app.services.account_service import AccountService
        from app.services.position_scoring_service import PositionScoringService
        
        # 1. 获取持仓
        account_service = AccountService(session, account_id)
        positions = await account_service.get_current_positions()
        
        # 2. 过滤标的
        if symbols:
            positions = [p for p in positions if p.symbol in symbols]
        
        if not positions:
            return {
                "success": True,
                "message": "没有需要刷新的持仓",
                "refreshed_count": 0
            }
        
        # 3. 强制刷新（use_cache=False）
        scoring_service = PositionScoringService(session, account_id)
        position_data = [
            {
                "symbol": p.symbol,
                "current_price": p.market_value / p.quantity,
                "position_size": p.market_value
            }
            for p in positions
        ]
        
        scores = await scoring_service.batch_calculate_scores(position_data)
        
        return {
            "success": True,
            "message": f"成功刷新{len(scores)}个持仓",
            "refreshed_count": len(scores),
            "symbols": [s.symbol for s in scores]
        }
        
    except Exception as e:
        logger.error(f"Failed to refresh positions: {e}")
        raise HTTPException(status_code=500, detail="刷新持仓评分失败")
```

---

### 2.5 获取宏观风险总览

```python
@router.get(
    "/macro/risk/overview",
    response_model=MacroRiskOverviewResponse,
    summary="获取宏观风险总览",
    description="获取5维度宏观风险评估和关键事件"
)
async def get_macro_risk_overview(
    use_cache: bool = Query(True, description="是否使用缓存"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取宏观风险总览
    
    流程:
    1. 调用MacroRiskScoringService计算5维度风险
    2. 获取关键地缘政治事件
    3. 生成风险预警
    4. 返回完整的风险分析报告
    
    参数:
    - use_cache: 是否使用缓存（6小时有效期）
    
    返回:
    - MacroRiskOverviewResponse: 宏观风险总览
    
    错误码:
    - 500: 分析失败
    """
    
    try:
        from app.services.macro_risk_scoring_service import MacroRiskScoringService
        risk_service = MacroRiskScoringService(session)
        
        result = await risk_service.get_macro_risk_overview(use_cache=use_cache)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get macro risk overview: {e}")
        raise HTTPException(status_code=500, detail="获取宏观风险失败")
```

---

### 2.6 获取货币政策分析

```python
@router.get(
    "/macro/monetary-policy",
    response_model=MonetaryPolicyDTO,
    summary="获取货币政策分析",
    description="获取利率、通胀、货币供应等货币政策指标"
)
async def get_monetary_policy(
    use_cache: bool = Query(True, description="是否使用缓存"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取货币政策分析
    
    流程:
    1. 从MacroIndicatorsService获取货币政策数据
    2. 返回利率、通胀、收益率曲线等指标
    
    参数:
    - use_cache: 是否使用缓存
    
    返回:
    - MonetaryPolicyDTO: 货币政策指标
    
    错误码:
    - 500: 获取失败
    """
    
    try:
        from app.services.macro_indicators_service import MacroIndicatorsService
        indicators_service = MacroIndicatorsService(session)
        
        result = await indicators_service.get_monetary_policy(use_cache=use_cache)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get monetary policy: {e}")
        raise HTTPException(status_code=500, detail="获取货币政策数据失败")
```

---

### 2.7 获取地缘政治事件

```python
@router.get(
    "/macro/geopolitical-events",
    response_model=List[GeopoliticalEventDTO],
    summary="获取地缘政治事件",
    description="获取最近的地缘政治新闻和事件"
)
async def get_geopolitical_events(
    days: int = Query(7, ge=1, le=30, description="查询最近N天的事件"),
    category: Optional[str] = Query(None, description="事件类别筛选"),
    min_severity: Optional[int] = Query(None, ge=1, le=10, description="最低严重度筛选"),
    session: AsyncSession = Depends(get_session)
):
    """
    获取地缘政治事件
    
    流程:
    1. 从GeopoliticalEventsService获取事件列表
    2. 根据参数过滤
    3. 按严重度排序返回
    
    参数:
    - days: 查询最近N天，默认7天
    - category: 可选，事件类别过滤
    - min_severity: 可选，最低严重度过滤
    
    返回:
    - List[GeopoliticalEventDTO]: 事件列表
    
    错误码:
    - 400: 参数错误
    - 500: 获取失败
    """
    
    try:
        from app.services.geopolitical_events_service import GeopoliticalEventsService
        geo_service = GeopoliticalEventsService(session)
        
        # 获取事件
        events = await geo_service.get_recent_events(days=days)
        
        # 过滤
        if category:
            events = [e for e in events if e.event_category == category]
        
        if min_severity:
            events = [e for e in events if e.severity >= min_severity]
        
        # 转换为DTO并排序
        event_dtos = [
            GeopoliticalEventDTO(
                event_date=e.event_date,
                category=e.event_category,
                title=e.event_title,
                description=e.event_description,
                severity=e.severity,
                affected_regions=e.affected_regions.split(",") if e.affected_regions else [],
                affected_industries=e.affected_industries.split(",") if e.affected_industries else [],
                market_impact_score=e.market_impact_score,
                source_url=e.source_url
            )
            for e in events
        ]
        
        # 按严重度降序排序
        event_dtos.sort(key=lambda x: x.severity, reverse=True)
        
        return event_dtos
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get geopolitical events: {e}")
        raise HTTPException(status_code=500, detail="获取地缘政治事件失败")
```

---

### 2.8 刷新宏观数据

```python
@router.post(
    "/macro/refresh",
    response_model=Dict[str, Any],
    summary="刷新宏观数据",
    description="强制刷新所有宏观指标和风险评分"
)
async def refresh_macro_data(
    session: AsyncSession = Depends(get_session)
):
    """
    刷新宏观数据
    
    流程:
    1. 刷新FRED经济指标
    2. 刷新地缘政治事件
    3. 重新计算风险评分
    4. 返回刷新结果
    
    返回:
    - 刷新结果统计
    
    错误码:
    - 500: 刷新失败
    
    注意:
    - 此操作较耗时（10-30秒）
    - 建议通过定时任务调用，而非用户手动触发
    """
    
    try:
        from app.services.macro_indicators_service import MacroIndicatorsService
        from app.services.geopolitical_events_service import GeopoliticalEventsService
        from app.services.macro_risk_scoring_service import MacroRiskScoringService
        
        results = {}
        
        # 1. 刷新宏观指标
        indicators_service = MacroIndicatorsService(session)
        indicators_result = await indicators_service.refresh_all_indicators()
        results["indicators"] = indicators_result
        
        # 2. 刷新地缘政治事件
        geo_service = GeopoliticalEventsService(session)
        events = await geo_service.fetch_recent_events(days=7)
        results["geopolitical_events"] = {
            "success": len(events),
            "count": len(events)
        }
        
        # 3. 重新计算风险评分
        risk_service = MacroRiskScoringService(session)
        risk_overview = await risk_service.get_macro_risk_overview(use_cache=False)
        results["risk_score"] = {
            "overall_score": risk_overview.overall_risk.score,
            "risk_level": risk_overview.overall_risk.level
        }
        
        return {
            "success": True,
            "message": "宏观数据刷新完成",
            "results": results,
            "refreshed_at": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Failed to refresh macro data: {e}")
        raise HTTPException(status_code=500, detail="刷新宏观数据失败")
```

---

## 3. 通用设计

### 3.1 依赖注入

```python
# app/routers/position_macro.py

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import get_session

async def get_current_account_id() -> str:
    """
    获取当前账户ID
    
    TODO: 从JWT token或session中获取
    目前返回固定值用于开发
    """
    return "default_account"

# 在端点中使用
@router.get("/positions/assessment")
async def get_positions_assessment(
    session: AsyncSession = Depends(get_session),
    account_id: str = Depends(get_current_account_id)
):
    # ...
```

### 3.2 错误处理

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

@router.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """处理值错误"""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)}
    )

@router.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """处理通用异常"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
```

### 3.3 请求日志

```python
from fastapi import Request
import time

@router.middleware("http")
async def log_requests(request: Request, call_next):
    """记录请求日志"""
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(
        f"{request.method} {request.url.path} "
        f"completed in {process_time:.2f}s "
        f"with status {response.status_code}"
    )
    
    return response
```

### 3.4 响应缓存（可选）

```python
from fastapi_cache.decorator import cache

@router.get("/macro/risk/overview")
@cache(expire=3600)  # 缓存1小时
async def get_macro_risk_overview(
    use_cache: bool = True,
    session: AsyncSession = Depends(get_session)
):
    # ...
```

---

## 4. 测试用例

### 4.1 单元测试

```python
# tests/test_position_macro_api.py

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_positions_assessment(async_client: AsyncClient):
    """测试获取持仓评估"""
    response = await async_client.get("/api/v1/positions/assessment")
    
    assert response.status_code == 200
    data = response.json()
    assert "positions" in data
    assert "portfolio_summary" in data

@pytest.mark.asyncio
async def test_get_technical_analysis(async_client: AsyncClient):
    """测试技术分析"""
    response = await async_client.get("/api/v1/positions/AAPL/technical")
    
    assert response.status_code == 200
    data = response.json()
    assert "trend" in data
    assert "rsi" in data
    assert "score" in data

@pytest.mark.asyncio
async def test_invalid_symbol(async_client: AsyncClient):
    """测试无效symbol"""
    response = await async_client.get("/api/v1/positions/INVALID123456/technical")
    
    assert response.status_code in [400, 404]
```

---

## 5. 实现检查清单

- [ ] 完善 `app/routers/position_macro.py` 中的8个端点
- [ ] 实现依赖注入（session, account_id）
- [ ] 添加参数验证（Query, Path, Body）
- [ ] 实现错误处理（HTTPException）
- [ ] 添加请求日志
- [ ] 编写API文档（docstring）
- [ ] 编写单元测试
- [ ] 集成测试
- [ ] 性能测试（每个端点 < 2s）
- [ ] 添加Swagger文档示例

---

**预计工作量**: 6-8小时
**优先级**: P0 (核心功能)
**依赖**: 所有Service层完成
