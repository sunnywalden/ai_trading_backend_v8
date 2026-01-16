"""
API监控路由

提供API调用统计、Rate Limit监控和警告信息
"""

from fastapi import APIRouter, Query
from typing import Dict, Any, List

from app.services.api_monitoring_service import api_monitor, APIProvider, APIRateLimit

router = APIRouter(tags=["API Monitoring"])


@router.get("/stats/{provider}", summary="获取特定API的统计数据")
async def get_api_stats(
    provider: APIProvider,
    time_range: str = Query("day", pattern="^(day|hour|minute)$")
) -> Dict[str, Any]:
    """
    获取指定API提供商的统计数据
    
    Args:
        provider: API提供商 (FRED/NewsAPI/Tiger/YahooFinance/OpenAI)
        time_range: 时间范围 (day/hour/minute)
    
    Returns:
        包含调用次数、成功率、Rate Limit使用情况等的统计数据
    """
    return await api_monitor.get_api_stats(provider, time_range)


@router.get("/stats", summary="获取所有API的统计数据")
async def get_all_api_stats(
    time_range: str = Query("day", pattern="^(day|hour|minute)$")
) -> List[Dict[str, Any]]:
    """
    获取所有API提供商的统计数据
    
    Args:
        time_range: 时间范围 (day/hour/minute)
    
    Returns:
        所有API的统计数据列表
    """
    return await api_monitor.get_all_api_stats(time_range)


@router.get("/report", summary="生成完整的监控报告")
async def get_monitoring_report() -> Dict[str, Any]:
    """
    生成完整的API监控报告
    
    包含：
    - 所有API的日/时统计
    - 告警信息（达到阈值的API）
    - 最近的错误记录
    - Rate Limit策略摘要
    
    Returns:
        综合监控报告
    """
    return await api_monitor.generate_monitoring_report()


@router.get("/rate-limit/{provider}", summary="检查API的Rate Limit状态")
async def check_rate_limit(provider: APIProvider) -> Dict[str, Any]:
    """
    检查特定API的Rate Limit状态
    
    Args:
        provider: API提供商
    
    Returns:
        包含是否可以调用、使用率、剩余次数和建议的状态信息
    """
    return await api_monitor.check_rate_limit_status(provider)


@router.get("/policies", summary="获取所有API的Rate Limit策略")
async def get_rate_limit_policies() -> Dict[str, Dict[str, Any]]:
    """
    获取所有外部API的Rate Limit策略信息
    
    返回每个API的：
    - 日/时/分钟级别的请求限制
    - 政策描述
    - 文档链接
    - 上次检查日期
    
    Returns:
        所有API的Rate Limit策略字典
    """
    policies = {}
    for provider in APIProvider:
        policies[provider.value] = api_monitor.get_rate_limit_info(provider)
    return policies


@router.get("/policies/{provider}", summary="获取特定API的Rate Limit策略")
async def get_provider_rate_limit_policy(provider: APIProvider) -> Dict[str, Any]:
    """
    获取特定API的Rate Limit策略详情
    
    Args:
        provider: API提供商
    
    Returns:
        该API的完整Rate Limit策略信息
    """
    return api_monitor.get_rate_limit_info(provider)


@router.get("/monitoring/health", summary="API监控服务健康检查")
async def monitoring_health_check() -> Dict[str, Any]:
    """
    检查API监控服务的健康状态
    
    Returns:
        服务状态和基本信息
    """
    stats = await api_monitor.get_all_api_stats("day")
    
    # 统计各状态API数量
    normal_count = sum(1 for s in stats if s["status"] == "normal")
    warning_count = sum(1 for s in stats if s["status"] == "warning")
    critical_count = sum(1 for s in stats if s["status"] == "critical")
    
    # 判断整体健康状态
    if critical_count > 0:
        overall_status = "critical"
    elif warning_count > 0:
        overall_status = "warning"
    else:
        overall_status = "healthy"
    
    return {
        "status": overall_status,
        "total_apis": len(APIProvider),
        "normal": normal_count,
        "warning": warning_count,
        "critical": critical_count,
        "monitoring_active": True,
        "rate_limit_thresholds": {
            "warning": f"{int(APIRateLimit.WARNING_THRESHOLD * 100)}%",
            "critical": f"{int(APIRateLimit.CRITICAL_THRESHOLD * 100)}%"
        }
    }
