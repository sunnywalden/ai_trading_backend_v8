"""
API调用监控服务

功能：
1. 跟踪每个外部API的调用频率和次数
2. Redis存储调用统计数据
3. 检测是否接近Rate Limit
4. 生成监控报告
5. 支持告警通知

支持的API：
- FRED API (宏观数据)
- News API (地缘政治)
- Tiger API (行情数据)
- Yahoo Finance (备用行情)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import json

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)


class APIProvider(str, Enum):
    """外部API提供商"""
    FRED = "FRED"                  # Federal Reserve Economic Data
    NEWS_API = "NewsAPI"           # 新闻API
    TIGER = "Tiger"                # 老虎API
    YAHOO_FINANCE = "YahooFinance" # Yahoo财经
    OPENAI = "OpenAI"              # OpenAI API


class APIRateLimit:
    """API Rate Limit配置
    
    记录各个免费API的限制政策（截至2026年1月）
    """
    
    # 每个API的免费额度限制
    LIMITS = {
        APIProvider.FRED: {
            "requests_per_day": 120_000,
            "requests_per_hour": None,  # 无明确小时限制
            "requests_per_minute": None,
            "description": "FRED API免费无限制，但建议控制在120K/天以内",
            "docs_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
            "last_checked": "2026-01-09"
        },
        APIProvider.NEWS_API: {
            "requests_per_day": 100,    # 免费版100请求/天
            "requests_per_hour": None,
            "requests_per_minute": None,
            "description": "News API免费版: 100请求/天",
            "docs_url": "https://newsapi.org/pricing",
            "last_checked": "2026-01-09"
        },
        APIProvider.TIGER: {
            "requests_per_day": None,
            "requests_per_hour": 3600,  # 约1请求/秒
            "requests_per_minute": 60,
            "description": "Tiger API免费延迟行情，建议控制频率",
            "docs_url": "https://quant.itigerup.com/openapi/",
            "last_checked": "2026-01-09"
        },
        APIProvider.YAHOO_FINANCE: {
            "requests_per_day": 2000,   # 建议限制
            "requests_per_hour": 100,
            "requests_per_minute": 5,   # 非官方限制，避免被ban
            "description": "Yahoo Finance非官方API，建议控制频率避免被限制",
            "docs_url": "https://github.com/ranaroussi/yfinance",
            "last_checked": "2026-01-09"
        },
        APIProvider.OPENAI: {
            "requests_per_day": None,
            "requests_per_hour": None,
            "requests_per_minute": 3,   # 取决于订阅级别
            "description": "OpenAI API按token和TPM计费，免费tier限制较严",
            "docs_url": "https://platform.openai.com/docs/guides/rate-limits",
            "last_checked": "2026-01-09"
        }
    }
    
    # 告警阈值（使用量达到限制的百分比）
    WARNING_THRESHOLD = 0.7   # 70%
    CRITICAL_THRESHOLD = 0.9  # 90%
    DEFAULT_COOLDOWN_SECONDS = settings.API_RATE_LIMIT_COOLDOWN_SECONDS


class APIMonitoringService:
    """API调用监控服务"""
    
    def __init__(self):
        self.rate_limits = APIRateLimit.LIMITS
        
    async def record_api_call(
        self, 
        provider: APIProvider, 
        endpoint: str = "default",
        success: bool = True,
        response_time_ms: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        记录API调用
        
        Args:
            provider: API提供商
            endpoint: 调用的端点/方法名
            success: 是否成功
            response_time_ms: 响应时间（毫秒）
            error_message: 错误信息（如果失败）
        """
        now = datetime.now()
        
        # 构造Redis key
        date_key = now.strftime("%Y-%m-%d")
        hour_key = now.strftime("%Y-%m-%d-%H")
        minute_key = now.strftime("%Y-%m-%d-%H-%M")
        
        # 构造各时间级别的 key 对应关系
        time_levels = [
            ("day", date_key),
            ("hour", hour_key),
            ("minute", minute_key)
        ]
        
        # 记录各级别统计（包含总数和状态）
        status = "success" if success else "error"
        for tr_type, tr_key in time_levels:
            await self._increment_counter(provider, tr_type, tr_key)
            await self._increment_counter(provider, f"{tr_type}:{status}", tr_key)
        
        # 记录端点级别统计
        await self._increment_endpoint_counter(provider, endpoint, date_key)
        
        # 记录响应时间（用于性能监控）
        if response_time_ms is not None:
            await self._record_response_time(provider, endpoint, response_time_ms)
        
        # 记录错误详情
        if not success and error_message:
            await self._record_error(provider, endpoint, error_message, now)
            if self._is_rate_limit_error(error_message):
                await self.set_cooldown(provider, APIRateLimit.DEFAULT_COOLDOWN_SECONDS, error_message)
        
        # 检查是否接近限制
        await self._check_rate_limit_threshold(provider)

    async def can_call_provider(self, provider: APIProvider) -> Dict[str, Any]:
        """检查是否允许调用（考虑冷却与配额）。"""
        cooldown = await self._get_cooldown(provider)
        if cooldown:
            return {
                "can_call": False,
                "reason": cooldown.get("reason") or "in cooldown",
                "cooldown_until": cooldown.get("until"),
            }

        status = await self.check_rate_limit_status(provider)
        return {
            "can_call": status.get("can_call", True),
            "reason": status.get("reason") or "",
            "cooldown_until": None,
        }

    async def set_cooldown(self, provider: APIProvider, seconds: int, reason: str = "") -> None:
        """设置某个API的冷却期，避免连续触发限流。"""
        until = datetime.now() + timedelta(seconds=seconds)
        payload = {"until": until.isoformat(), "reason": reason}
        redis_key = f"api_monitor:{provider.value}:cooldown"
        await cache.set(redis_key, payload, expire=seconds)

    async def _get_cooldown(self, provider: APIProvider) -> Optional[Dict[str, Any]]:
        redis_key = f"api_monitor:{provider.value}:cooldown"
        return await cache.get(redis_key)
    
    async def get_api_stats(
        self, 
        provider: APIProvider,
        time_range: str = "day"
    ) -> Dict[str, Any]:
        """
        获取API统计数据
        
        Args:
            provider: API提供商
            time_range: 时间范围 (day/hour/minute)
            
        Returns:
            统计数据字典
        """
        now = datetime.now()
        
        if time_range == "day":
            key_suffix = now.strftime("%Y-%m-%d")
        elif time_range == "hour":
            key_suffix = now.strftime("%Y-%m-%d-%H")
        else:  # minute
            key_suffix = now.strftime("%Y-%m-%d-%H-%M")
        
        # 获取调用次数和状态统计
        # 优先使用新的 {time_range}:{status} 格式，兼容旧的 status:{status} 格式（仅限 day）
        total_calls = await self._get_counter(provider, time_range, key_suffix) or 0
        
        success_calls = await self._get_counter(provider, f"{time_range}:success", key_suffix)
        error_calls = await self._get_counter(provider, f"{time_range}:error", key_suffix)
        
        # 兼容性回退
        if time_range == "day" and success_calls is None and error_calls is None:
            success_calls = await self._get_counter(provider, "status:success", key_suffix)
            error_calls = await self._get_counter(provider, "status:error", key_suffix)
            
        success_calls = success_calls or 0
        error_calls = error_calls or 0
        
        # 确保数据一致性：如果总调用数大于成功+失败之和，说明部分状态记录已过期或未记录，将差额归为失败
        if total_calls > (success_calls + error_calls):
            error_calls = total_calls - success_calls
        
        # 获取限制信息
        limit_info = self.rate_limits.get(provider, {})
        limit_key = f"requests_per_{time_range}"
        rate_limit = limit_info.get(limit_key)
        
        # 计算使用率
        usage_percent = (total_calls / rate_limit * 100) if rate_limit else 0
        
        # 判断状态
        status = "normal"
        if rate_limit and usage_percent >= APIRateLimit.CRITICAL_THRESHOLD * 100:
            status = "critical"
        elif rate_limit and usage_percent >= APIRateLimit.WARNING_THRESHOLD * 100:
            status = "warning"
        
        return {
            "provider": provider.value,
            "time_range": time_range,
            "timestamp": now.isoformat(),
            "total_calls": total_calls,
            "success_calls": success_calls,
            "error_calls": error_calls,
            "success_rate": round(success_calls / total_calls * 100, 2) if total_calls > 0 else 100,
            "rate_limit": rate_limit,
            "usage_percent": round(usage_percent, 2),
            "status": status,
            "remaining": max(0, rate_limit - total_calls) if rate_limit else None
        }
    
    async def get_all_api_stats(self, time_range: str = "day") -> List[Dict[str, Any]]:
        """获取所有API的统计数据"""
        stats = []
        for provider in APIProvider:
            try:
                stat = await self.get_api_stats(provider, time_range)
                stats.append(stat)
            except Exception as e:
                logger.error(f"Failed to get stats for {provider.value}: {e}")
        return stats
    
    async def generate_monitoring_report(self) -> Dict[str, Any]:
        """
        生成监控报告
        
        Returns:
            包含所有API监控数据的综合报告
        """
        now = datetime.now()
        
        # 获取所有API的统计
        daily_stats = await self.get_all_api_stats("day")
        hourly_stats = await self.get_all_api_stats("hour")
        
        # 检测告警
        warnings = []
        critical_alerts = []
        
        for stat in daily_stats:
            if stat["status"] == "critical":
                critical_alerts.append({
                    "provider": stat["provider"],
                    "message": f"{stat['provider']} 已使用 {stat['usage_percent']}% 的日配额",
                    "remaining": stat["remaining"]
                })
            elif stat["status"] == "warning":
                warnings.append({
                    "provider": stat["provider"],
                    "message": f"{stat['provider']} 已使用 {stat['usage_percent']}% 的日配额",
                    "remaining": stat["remaining"]
                })
        
        # 获取错误详情
        recent_errors = await self._get_recent_errors()
        
        return {
            "generated_at": now.isoformat(),
            "summary": {
                "total_providers": len(APIProvider),
                "critical_alerts": len(critical_alerts),
                "warnings": len(warnings),
                "total_errors_today": sum(s["error_calls"] for s in daily_stats)
            },
            "daily_stats": daily_stats,
            "hourly_stats": hourly_stats,
            "critical_alerts": critical_alerts,
            "warnings": warnings,
            "recent_errors": recent_errors,
            "rate_limit_policies": self._get_rate_limit_summary()
        }
    
    async def check_rate_limit_status(self, provider: APIProvider) -> Dict[str, Any]:
        """
        检查特定API的Rate Limit状态
        
        Returns:
            包含状态和建议的字典
        """
        stats = await self.get_api_stats(provider, "day")
        
        can_call = True
        reason = ""
        suggestion = ""
        
        if stats["status"] == "critical":
            can_call = False
            reason = f"已达到日限额的 {stats['usage_percent']}%"
            suggestion = "建议使用缓存或等待明天"
        elif stats["status"] == "warning":
            suggestion = f"接近限额 ({stats['usage_percent']}%)，建议减少调用"
        
        return {
            "provider": provider.value,
            "can_call": can_call,
            "status": stats["status"],
            "usage_percent": stats["usage_percent"],
            "remaining": stats["remaining"],
            "reason": reason,
            "suggestion": suggestion
        }
    
    def get_rate_limit_info(self, provider: APIProvider) -> Dict[str, Any]:
        """获取API的Rate Limit策略信息"""
        return self.rate_limits.get(provider, {})
    
    # ========== 私有方法 ==========
    
    async def _increment_counter(self, provider: APIProvider, counter_type: str, key_suffix: str) -> None:
        """增加计数器"""
        redis_key = f"api_monitor:{provider.value}:{counter_type}:{key_suffix}"
        
        # 根据时间范围设置过期时间 (包含状态统计)
        if "day" in counter_type or counter_type.startswith("status:"):
            expire = 86400 * 7  # 保留7天
        elif "hour" in counter_type:
            expire = 3600 * 48  # 保留48小时
        else:  # minute
            expire = 3600       # 保留1小时
        
        # 获取当前值
        current = await cache.get(redis_key, is_json=False)
        count = int(current) if current else 0
        
        # 增加并设置过期
        await cache.set(redis_key, str(count + 1), expire=expire, is_json=False)
    
    async def _get_counter(self, provider: APIProvider, counter_type: str, key_suffix: str) -> Optional[int]:
        """获取计数器值"""
        redis_key = f"api_monitor:{provider.value}:{counter_type}:{key_suffix}"
        value = await cache.get(redis_key, is_json=False)
        return int(value) if value else None
    
    async def _increment_endpoint_counter(self, provider: APIProvider, endpoint: str, date_key: str) -> None:
        """记录端点级别统计"""
        redis_key = f"api_monitor:{provider.value}:endpoint:{endpoint}:{date_key}"
        
        current = await cache.get(redis_key, is_json=False)
        count = int(current) if current else 0
        await cache.set(redis_key, str(count + 1), expire=86400 * 7, is_json=False)
    
    async def _record_response_time(self, provider: APIProvider, endpoint: str, response_time_ms: float) -> None:
        """记录响应时间"""
        redis_key = f"api_monitor:{provider.value}:response_times:{endpoint}"
        
        # 获取历史数据（保留最近100次）
        data = await cache.get(redis_key)
        times = data if data else []
        
        times.append({
            "timestamp": datetime.now().isoformat(),
            "response_time_ms": response_time_ms
        })
        
        # 只保留最近100次
        if len(times) > 100:
            times = times[-100:]
        
        await cache.set(redis_key, times, expire=86400)
    
    async def _record_error(self, provider: APIProvider, endpoint: str, error_message: str, timestamp: datetime) -> None:
        """记录错误详情"""
        redis_key = f"api_monitor:{provider.value}:errors"
        
        # 获取错误列表
        errors = await cache.get(redis_key) or []
        
        errors.append({
            "timestamp": timestamp.isoformat(),
            "endpoint": endpoint,
            "error": error_message
        })
        
        # 只保留最近50条错误
        if len(errors) > 50:
            errors = errors[-50:]
        
        await cache.set(redis_key, errors, expire=86400 * 3)
    
    async def _get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的错误"""
        all_errors = []
        
        for provider in APIProvider:
            redis_key = f"api_monitor:{provider.value}:errors"
            errors = await cache.get(redis_key) or []
            
            for error in errors:
                all_errors.append({
                    "provider": provider.value,
                    **error
                })
        
        # 按时间排序，返回最近的
        all_errors.sort(key=lambda x: x["timestamp"], reverse=True)
        return all_errors[:limit]
    
    async def _check_rate_limit_threshold(self, provider: APIProvider) -> None:
        """检查是否达到告警阈值"""
        stats = await self.get_api_stats(provider, "day")
        
        if stats["status"] == "critical":
            logger.critical(
                f"🚨 {provider.value} API达到临界阈值！"
                f"已使用 {stats['usage_percent']}%，剩余 {stats['remaining']} 次"
            )
        elif stats["status"] == "warning":
            logger.warning(
                f"⚠️  {provider.value} API接近限额！"
                f"已使用 {stats['usage_percent']}%，剩余 {stats['remaining']} 次"
            )

    @staticmethod
    def _is_rate_limit_error(error_message: str) -> bool:
        msg = error_message.lower()
        return "rate limited" in msg or "too many requests" in msg or "429" in msg
    
    def _get_rate_limit_summary(self) -> Dict[str, Any]:
        """获取所有API的Rate Limit策略摘要"""
        summary = {}
        for provider, limits in self.rate_limits.items():
            summary[provider.value] = {
                "daily_limit": limits.get("requests_per_day"),
                "hourly_limit": limits.get("requests_per_hour"),
                "description": limits.get("description"),
                "last_checked": limits.get("last_checked"),
                "docs_url": limits.get("docs_url")
            }
        return summary


# 全局监控服务实例
api_monitor = APIMonitoringService()
