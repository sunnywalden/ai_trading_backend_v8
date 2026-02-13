"""
测试信号持仓联动功能

验证:
1. 信号类型智能推断（SignalEngine._infer_signal_type）
2. 信号持仓过滤器（SignalPositionFilter）
3. API集成（filter_by_position参数）
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, and_
from app.core.database import AsyncSessionLocal
from app.models.trading_signal import TradingSignal, SignalStatus, SignalType
from app.models.strategy import StrategyRun
from app.engine.signal_engine import SignalEngine
from app.engine.signal_position_filter import SignalPositionFilter


async def test_signal_type_inference():
    """测试信号类型智能推断"""
    print("\n" + "="*60)
    print("测试1: 信号类型智能推断")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        engine = SignalEngine(session)
        
        # 测试用例（模拟不同持仓情况）
        test_cases = [
            {
                "name": "无持仓 → ENTRY",
                "symbol": "AAPL",
                "direction": "LONG",
                "account_id": "test_account",
                "expected": SignalType.ENTRY
            },
            {
                "name": "有多头持仓 + LONG方向 → ADD",
                "symbol": "MSFT",
                "direction": "LONG",
                "account_id": "test_account",
                "expected": SignalType.ADD
            },
            {
                "name": "有多头持仓 + SHORT方向 → EXIT",
                "symbol": "GOOGL",
                "direction": "SHORT",
                "account_id": "test_account",
                "expected": SignalType.EXIT
            }
        ]
        
        for case in test_cases:
            result = await engine._infer_signal_type(
                symbol=case["symbol"],
                direction=case["direction"],
                account_id=case["account_id"]
            )
            status = "✅" if result == case["expected"] else "❌"
            print(f"{status} {case['name']}")
            print(f"   预期: {case['expected'].value}, 实际: {result.value}")


async def test_signal_filtering():
    """测试信号持仓过滤"""
    print("\n" + "="*60)
    print("测试2: 信号持仓过滤")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        # 获取待执行信号
        stmt = (
            select(TradingSignal)
            .where(TradingSignal.status == SignalStatus.VALIDATED)
            .limit(10)
        )
        result = await session.execute(stmt)
        signals = result.scalars().all()
        
        if not signals:
            print("❌ 没有找到待执行信号，跳过测试")
            return
        
        print(f"原始信号数量: {len(signals)}")
        for signal in signals:
            print(f"  - {signal.symbol} | {signal.signal_type.value} | {signal.direction}")
        
        # 应用过滤器
        filter_service = SignalPositionFilter(session)
        account_id = signals[0].account_id if signals else "default_account"
        
        filtered_signals, filter_stats = await filter_service.filter_signals_with_positions(
            signals=signals,
            account_id=account_id
        )
        
        print(f"\n过滤后信号数量: {len(filtered_signals)}")
        print(f"过滤统计: {filter_stats}")
        
        # 显示被过滤的信号
        filtered_out = [s for s in signals if s not in filtered_signals]
        if filtered_out:
            print(f"\n被过滤的信号 ({len(filtered_out)}个):")
            for signal in filtered_out:
                print(f"  ❌ {signal.symbol} | {signal.signal_type.value} | {signal.direction}")


async def test_api_integration():
    """测试API集成（模拟）"""
    print("\n" + "="*60)
    print("测试3: API集成验证")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        # 查询信号
        stmt = (
            select(TradingSignal)
            .where(TradingSignal.status == SignalStatus.VALIDATED)
            .limit(5)
        )
        result = await session.execute(stmt)
        signals = result.scalars().all()
        
        if not signals:
            print("❌ 没有待执行信号")
            return
        
        print(f"✅ 找到 {len(signals)} 个待执行信号")
        
        # 测试不启用过滤
        print("\n不启用过滤 (filter_by_position=False):")
        print(f"  返回信号数: {len(signals)}")
        
        # 测试启用过滤
        print("\n启用过滤 (filter_by_position=True):")
        filter_service = SignalPositionFilter(session)
        account_id = signals[0].account_id if signals else "default_account"
        filtered_signals, filter_stats = await filter_service.filter_signals_with_positions(
            signals=signals,
            account_id=account_id
        )
        print(f"  返回信号数: {len(filtered_signals)}")
        print(f"  过滤统计: {filter_stats}")
        
        # 验证extra_metadata
        if filtered_signals:
            sample = filtered_signals[0]
            print(f"\n信号示例 ({sample.symbol}):")
            print(f"  signal_type: {sample.signal_type.value}")
            print(f"  direction: {sample.direction}")
            print(f"  status: {sample.status.value}")


async def test_complete_flow():
    """测试完整流程"""
    print("\n" + "="*60)
    print("测试4: 完整流程测试")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        # 1. 查找一个已完成的策略运行
        stmt = (
            select(StrategyRun)
            .where(StrategyRun.status == "COMPLETED")
            .order_by(StrategyRun.end_time.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        strategy_run = result.scalars().first()
        
        if not strategy_run:
            print("❌ 没有找到已完成的策略运行")
            return
        
        print(f"✅ 使用策略运行: {strategy_run.id}")
        print(f"   策略: {strategy_run.strategy_id}")
        print(f"   方向: {strategy_run.direction}")
        
        # 2. 生成信号（带智能类型推断）
        engine = SignalEngine(session)
        signals = await engine.generate_signals_from_strategy_run(
            strategy_run_id=strategy_run.id,
            max_signals=5
        )
        
        print(f"\n✅ 生成 {len(signals)} 个信号")
        for signal in signals:
            print(f"  - {signal.symbol} | {signal.signal_type.value} | "
                  f"方向: {signal.direction} | 强度: {signal.signal_strength:.0f}")
        
        # 3. 应用持仓过滤
        if signals:
            filter_service = SignalPositionFilter(session)
            filtered_signals, filter_stats = await filter_service.filter_signals_with_positions(
                signals=signals,
                account_id=strategy_run.account_id
            )
            
            print(f"\n✅ 过滤后剩余 {len(filtered_signals)} 个信号")
            print(f"   过滤统计: {filter_stats}")
            
            # 显示被过滤的信号
            if len(filtered_signals) < len(signals):
                filtered_out = [s for s in signals if s not in filtered_signals]
                print(f"\n   被过滤信号:")
                for signal in filtered_out:
                    print(f"   ❌ {signal.symbol} | {signal.signal_type.value}")


async def main():
    """运行所有测试"""
    print("\n🚀 开始测试信号持仓联动功能\n")
    
    try:
        await test_signal_type_inference()
        await test_signal_filtering()
        await test_api_integration()
        await test_complete_flow()
        
        print("\n" + "="*60)
        print("✅ 所有测试完成")
        print("="*60)
        
        print("\n📝 下一步操作:")
        print("1. 重启后端服务: uvicorn app.main:app --reload")
        print("2. 测试API: GET /quant-loop/signals/pending?filter_by_position=true")
        print("3. 在前端打开持仓过滤开关")
        print("4. 观察信号列表的变化（信号类型、当前持仓）")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
