"""
清理重复信号脚本

功能：
1. 查找数据库中重复的交易信号（相同symbol + account_id)
2. 保留每个symbol信号强度最高的信号
3. 将其他重复信号标记为已过期

使用方法：
    python clean_duplicate_signals.py [--dry-run]
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import argparse
from datetime import datetime
from typing import Dict, List
from collections import defaultdict

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session
from app.models.trading_signal import TradingSignal, SignalStatus
# 导入相关模型以确保SQLAlchemy关系正确配置
from app.models.strategy import Strategy, StrategyRun


async def find_duplicate_signals(session: AsyncSession) -> Dict[str, List[TradingSignal]]:
    """查找重复的信号（按symbol+account_id分组）"""
    
    # 查询所有活跃信号
    stmt = (
        select(TradingSignal)
        .where(TradingSignal.status.in_([SignalStatus.GENERATED, SignalStatus.VALIDATED]))
        .order_by(TradingSignal.symbol, desc(TradingSignal.signal_strength))
    )
    
    result = await session.execute(stmt)
    all_signals = result.scalars().all()
    
    # 按 (symbol, account_id) 分组
    signal_groups: Dict[str, List[TradingSignal]] = defaultdict(list)
    for signal in all_signals:
        key = f"{signal.symbol}_{signal.account_id}"
        signal_groups[key].append(signal)
    
    # 筛选出有重复的组
    duplicate_groups = {k: v for k, v in signal_groups.items() if len(v) > 1}
    
    return duplicate_groups


async def clean_duplicates(session: AsyncSession, dry_run: bool = True):
    """清理重复信号"""
    
    print("🔍 开始扫描重复信号...")
    duplicate_groups = await find_duplicate_signals(session)
    
    if not duplicate_groups:
        print("✅ 未发现重复信号，数据库状态良好！")
        return
    
    print(f"\n⚠️  发现 {len(duplicate_groups)} 组重复信号：\n")
    
    total_duplicates = 0
    kept_signals = []
    expired_signals = []
    
    for group_key, signals in duplicate_groups.items():
        symbol = signals[0].symbol
        account_id = signals[0].account_id
        
        # 第一个信号（信号强度最高）保留，其他标记为过期
        keep_signal = signals[0]
        duplicate_signals = signals[1:]
        
        kept_signals.append(keep_signal)
        expired_signals.extend(duplicate_signals)
        
        print(f"📊 {symbol} (账户: {account_id})")
        print(f"   - 共 {len(signals)} 个信号")
        print(f"   - ✅ 保留: signal_id={keep_signal.signal_id[:8]}..., 强度={keep_signal.signal_strength:.1f}%")
        
        for dup_signal in duplicate_signals:
            print(f"   - ❌ 过期: signal_id={dup_signal.signal_id[:8]}..., 强度={dup_signal.signal_strength:.1f}%")
            total_duplicates += 1
        
        print()
    
    print(f"\n📈 统计汇总:")
    print(f"   - 重复信号组: {len(duplicate_groups)}")
    print(f"   - 保留信号: {len(kept_signals)}")
    print(f"   - 需清理: {total_duplicates}")
    
    if dry_run:
        print("\n🔒 DRY RUN 模式：不会修改数据库")
        print("   运行 'python clean_duplicate_signals.py --execute' 执行清理")
        return
    
    # 执行清理
    print("\n🚀 开始执行清理...")
    for signal in expired_signals:
        signal.status = SignalStatus.EXPIRED
        signal.expired_at = datetime.utcnow()
    
    await session.commit()
    print(f"✅ 已清理 {total_duplicates} 个重复信号！")


async def get_signal_statistics(session: AsyncSession):
    """获取信号统计信息"""
    
    # 按状态统计
    stmt = (
        select(
            TradingSignal.status,
            func.count(TradingSignal.signal_id).label('count')
        )
        .group_by(TradingSignal.status)
    )
    
    result = await session.execute(stmt)
    status_counts = result.all()
    
    print("\n📊 当前信号状态统计:")
    for status, count in status_counts:
        print(f"   - {status.value}: {count}")
    
    # 按symbol统计活跃信号
    stmt = (
        select(
            TradingSignal.symbol,
            func.count(TradingSignal.signal_id).label('count')
        )
        .where(TradingSignal.status.in_([SignalStatus.GENERATED, SignalStatus.VALIDATED]))
        .group_by(TradingSignal.symbol)
        .having(func.count(TradingSignal.signal_id) > 1)
        .order_by(desc('count'))
    )
    
    result = await session.execute(stmt)
    symbol_counts = result.all()
    
    if symbol_counts:
        print("\n🔁 重复信号最多的标的:")
        for symbol, count in symbol_counts[:10]:
            print(f"   - {symbol}: {count} 个信号")


async def main():
    parser = argparse.ArgumentParser(description='清理重复交易信号')
    parser.add_argument('--execute', action='store_true', help='实际执行清理（默认为dry-run模式）')
    parser.add_argument('--stats', action='store_true', help='仅显示统计信息')
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    print("=" * 60)
    print("🧹 交易信号去重清理工具")
    print("=" * 60)
    
    session = None
    try:
        async for session in get_session():
            try:
                if args.stats:
                    await get_signal_statistics(session)
                else:
                    await get_signal_statistics(session)
                    await clean_duplicates(session, dry_run=dry_run)
            except Exception as e:
                print(f"❌ 错误: {str(e)}")
                import traceback
                traceback.print_exc()
            break
    except Exception as e:
        print(f"❌ 数据库连接错误: {str(e)}")
    finally:
        # 确保正确关闭session
        if session:
            await session.close()


if __name__ == "__main__":
    asyncio.run(main())
