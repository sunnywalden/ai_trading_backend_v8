"""
API监控路由

提供API调用统计、Rate Limit监控和警告信息
"""

from fastapi import APIRouter, Query, Depends
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from app.services.api_monitoring_service import api_monitor, APIProvider, APIRateLimit
from app.models.db import redis_client, get_session
from app.core.auth import get_current_user
from sqlalchemy.ext.asyncio import AsyncSession

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
        "monitoring_enabled": True,
        "redis_enabled": redis_client is not None,
        "last_updated": datetime.now().isoformat(),
        "rate_limit_thresholds": {
            "warning": f"{int(APIRateLimit.WARNING_THRESHOLD * 100)}%",
            "critical": f"{int(APIRateLimit.CRITICAL_THRESHOLD * 100)}%"
        }
    }


@router.get("/llm-stats", summary="V10.4 M1 — LLM 调用统计（llm_call_log）")
async def get_llm_stats(
    hours: int = Query(24, ge=1, le=168, description="统计时间窗口（小时），最多 7 天"),
    session: AsyncSession = Depends(get_session),
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    查询最近 N 小时内的 LLM 调用统计。

    返回：
    - total        : 总调用次数
    - success      : 成功次数
    - timeout      : 超时次数
    - rate_limited : 被限速次数
    - error        : 错误次数
    - degraded     : 降级调用次数（非首选提供商）
    - p50_latency_ms / p95_latency_ms : 延迟分位数
    - by_model     : 按模型分组统计
    - by_caller    : 按调用方分组统计
    """
    from sqlalchemy import text

    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    try:
        # ── 聚合统计 ──
        agg_sql = text(
            """
            SELECT
                COUNT(*)                                         AS total,
                SUM(CASE WHEN status='SUCCESS'      THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN status='TIMEOUT'      THEN 1 ELSE 0 END) AS timeout,
                SUM(CASE WHEN status='RATE_LIMITED' THEN 1 ELSE 0 END) AS rate_limited,
                SUM(CASE WHEN status='ERROR'        THEN 1 ELSE 0 END) AS error_count,
                SUM(CASE WHEN degraded=1            THEN 1 ELSE 0 END) AS degraded,
                AVG(latency_ms)                                  AS avg_latency_ms
            FROM llm_call_log
            WHERE created_at >= :since
            """
        )
        row = (await session.execute(agg_sql, {"since": since})).fetchone()
        row = row if row is not None else (0, 0, 0, 0, 0, 0, None)
        total       = int(row[0] or 0)
        success     = int(row[1] or 0)
        timeout_cnt = int(row[2] or 0)
        rate_limited= int(row[3] or 0)
        error_count = int(row[4] or 0)
        degraded    = int(row[5] or 0)
        avg_lat     = round(float(row[6] or 0), 1)

        # ── 延迟分位数（取最近 1000 条排序后近似） ──
        lat_sql = text(
            "SELECT latency_ms FROM llm_call_log "
            "WHERE created_at >= :since AND status='SUCCESS' "
            "ORDER BY latency_ms LIMIT 1000"
        )
        lat_rows = (await session.execute(lat_sql, {"since": since})).fetchall()
        lat_vals = sorted([r[0] for r in lat_rows if r[0] is not None])
        p50 = lat_vals[int(len(lat_vals) * 0.5)] if lat_vals else None
        p95 = lat_vals[int(len(lat_vals) * 0.95)] if lat_vals else None

        # ── 按 model 分组 ──
        model_sql = text(
            "SELECT model, COUNT(*) AS cnt "
            "FROM llm_call_log WHERE created_at >= :since "
            "GROUP BY model ORDER BY cnt DESC LIMIT 10"
        )
        by_model = [
            {"model": r[0], "count": int(r[1])}
            for r in (await session.execute(model_sql, {"since": since})).fetchall()
        ]

        # ── 按 caller 分组 ──
        caller_sql = text(
            "SELECT caller, COUNT(*) AS cnt "
            "FROM llm_call_log WHERE created_at >= :since "
            "GROUP BY caller ORDER BY cnt DESC LIMIT 20"
        )
        by_caller = [
            {"caller": r[0], "count": int(r[1])}
            for r in (await session.execute(caller_sql, {"since": since})).fetchall()
        ]

        error_rate = round((error_count + timeout_cnt) / total * 100, 2) if total else 0.0

        return {
            "window_hours": hours,
            "since": since.isoformat(),
            "total": total,
            "success": success,
            "timeout": timeout_cnt,
            "rate_limited": rate_limited,
            "error": error_count,
            "degraded": degraded,
            "error_rate_pct": error_rate,
            "avg_latency_ms": avg_lat,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "by_model": by_model,
            "by_caller": by_caller,
        }

    except Exception as exc:
        # llm_call_log 表可能尚未创建（冷启动期间），返回空统计而不是 500
        return {
            "window_hours": hours,
            "since": since.isoformat(),
            "total": 0,
            "success": 0, "timeout": 0, "rate_limited": 0,
            "error": 0, "degraded": 0, "error_rate_pct": 0.0,
            "avg_latency_ms": None, "p50_latency_ms": None, "p95_latency_ms": None,
            "by_model": [], "by_caller": [],
            "_note": f"llm_call_log 查询失败（可能表尚未创建）: {str(exc)[:120]}",
        }
