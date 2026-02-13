#!/usr/bin/env python3
"""
API监控服务测试脚本

测试API监控功能是否正常工作
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.api_monitoring_service import api_monitor, APIProvider


async def test_record_api_calls():
    """测试记录API调用"""
    print("\n=== 测试1: 记录API调用 ===")
    
    # 模拟FRED API调用
    await api_monitor.record_api_call(
        provider=APIProvider.FRED,
        endpoint="get_series:DFF",
        success=True,
        response_time_ms=250.5
    )
    print("✓ 记录FRED API调用成功")
    
    # 模拟News API调用（失败）
    await api_monitor.record_api_call(
        provider=APIProvider.NEWS_API,
        endpoint="get_everything",
        success=False,
        response_time_ms=1500.0,
        error_message="Rate limit exceeded"
    )
    print("✓ 记录News API调用失败")


async def test_get_stats():
    """测试获取统计数据"""
    print("\n=== 测试2: 获取统计数据 ===")
    
    # 获取FRED统计
    fred_stats = await api_monitor.get_api_stats(APIProvider.FRED, "day")
    print(f"FRED 今日调用: {fred_stats['total_calls']}")
    print(f"  成功率: {fred_stats['success_rate']}%")
    print(f"  使用率: {fred_stats['usage_percent']}%")
    print(f"  状态: {fred_stats['status']}")
    
    # 获取所有API统计
    all_stats = await api_monitor.get_all_api_stats("day")
    print(f"\n所有API统计（共{len(all_stats)}个提供商）:")
    for stat in all_stats:
        print(f"  - {stat['provider']}: {stat['total_calls']}次调用, {stat['status']}")


async def test_rate_limit_check():
    """测试Rate Limit检查"""
    print("\n=== 测试3: Rate Limit检查 ===")
    
    for provider in [APIProvider.FRED, APIProvider.NEWS_API, APIProvider.TIGER]:
        status = await api_monitor.check_rate_limit_status(provider)
        print(f"\n{provider.value}:")
        print(f"  可调用: {status['can_call']}")
        print(f"  状态: {status['status']}")
        print(f"  使用率: {status['usage_percent']}%")
        if status['remaining']:
            print(f"  剩余: {status['remaining']} 次")
        if status['suggestion']:
            print(f"  建议: {status['suggestion']}")


async def test_monitoring_report():
    """测试生成监控报告"""
    print("\n=== 测试4: 生成监控报告 ===")
    
    report = await api_monitor.generate_monitoring_report()
    
    print(f"\n报告生成时间: {report['generated_at']}")
    print(f"\n概要:")
    print(f"  总提供商: {report['summary']['total_providers']}")
    print(f"  临界告警: {report['summary']['critical_alerts']}")
    print(f"  警告: {report['summary']['warnings']}")
    print(f"  今日错误: {report['summary']['total_errors_today']}")
    
    if report['critical_alerts']:
        print(f"\n🚨 临界告警:")
        for alert in report['critical_alerts']:
            print(f"  - {alert['provider']}: {alert['message']}")
    
    if report['warnings']:
        print(f"\n⚠️  警告:")
        for warning in report['warnings']:
            print(f"  - {warning['provider']}: {warning['message']}")
    
    if report['recent_errors']:
        print(f"\n最近错误:")
        for error in report['recent_errors'][:3]:  # 只显示前3个
            print(f"  - [{error['timestamp']}] {error['provider']}.{error['endpoint']}: {error['error']}")


async def test_rate_limit_policies():
    """测试获取Rate Limit策略"""
    print("\n=== 测试5: Rate Limit策略 ===")
    
    for provider in APIProvider:
        policy = api_monitor.get_rate_limit_info(provider)
        print(f"\n{provider.value}:")
        print(f"  日限制: {policy.get('requests_per_day') or '无限制'}")
        print(f"  小时限制: {policy.get('requests_per_hour') or '无限制'}")
        print(f"  分钟限制: {policy.get('requests_per_minute') or '无限制'}")
        print(f"  描述: {policy.get('description', 'N/A')}")
        print(f"  文档: {policy.get('docs_url', 'N/A')}")
        print(f"  更新: {policy.get('last_checked', 'N/A')}")


async def test_multiple_calls():
    """测试多次调用累积"""
    print("\n=== 测试6: 模拟多次API调用 ===")
    
    # 模拟10次FRED调用
    for i in range(10):
        await api_monitor.record_api_call(
            provider=APIProvider.FRED,
            endpoint=f"get_series:TEST{i}",
            success=True,
            response_time_ms=100.0 + i * 10
        )
    
    print("✓ 已记录10次FRED API调用")
    
    # 获取更新后的统计
    stats = await api_monitor.get_api_stats(APIProvider.FRED, "day")
    print(f"FRED 今日总调用: {stats['total_calls']}")
    print(f"使用率: {stats['usage_percent']}%")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("API监控服务测试")
    print("=" * 60)
    
    try:
        await test_record_api_calls()
        await test_get_stats()
        await test_rate_limit_check()
        await test_monitoring_report()
        await test_rate_limit_policies()
        await test_multiple_calls()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
