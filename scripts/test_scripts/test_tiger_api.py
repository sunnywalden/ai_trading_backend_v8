#!/usr/bin/env python3
"""Tiger Open API 连接测试脚本

用于验证 Tiger API 配置是否正确。

说明：该脚本已从项目根目录归档到 scripts/test_scripts/。
"""

import asyncio
import sys
from pathlib import Path

# 确保无论从哪里执行，都能正确导入项目根目录下的 `app` 包
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.broker.factory import make_option_broker_client
from app.broker.history_factory import make_trade_history_client


async def test_option_client() -> bool:
    """测试期权客户端"""
    print("=" * 60)
    print("测试期权客户端 (OptionBrokerClient)")
    print("=" * 60)

    try:
        client = make_option_broker_client()
        print(f"✓ 客户端类型: {type(client).__name__}")

        # 测试获取股票持仓
        print("\n正在获取股票持仓...")
        underlying_positions = await client.list_underlying_positions(settings.TIGER_ACCOUNT)
        print(f"✓ 股票持仓数量: {len(underlying_positions)}")

        if underlying_positions:
            for pos in underlying_positions[:3]:
                print(f"  - {pos.symbol}: {pos.quantity} 股 @ ${pos.last_price:.2f}")

        # 测试获取期权持仓
        print("\n正在获取期权持仓...")
        option_positions = await client.list_option_positions(settings.TIGER_ACCOUNT)
        print(f"✓ 期权持仓数量: {len(option_positions)}")

        if option_positions:
            for pos in option_positions[:3]:
                print(
                    f"  - {pos.contract.underlying} {pos.contract.right} "
                    f"${pos.contract.strike}: {pos.quantity} 张"
                )
                print(f"    Delta={pos.greeks.delta:.4f}, Gamma={pos.greeks.gamma:.4f}")

        print("\n✓ 期权客户端测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 期权客户端测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_history_client() -> bool:
    """测试历史成交客户端"""
    print("\n" + "=" * 60)
    print("测试历史成交客户端 (TradeHistoryClient)")
    print("=" * 60)

    try:
        from datetime import datetime, timedelta

        client = make_trade_history_client()
        print(f"✓ 客户端类型: {type(client).__name__}")

        # 查询最近7天的成交记录
        end = datetime.utcnow()
        start = end - timedelta(days=7)

        print(f"\n正在查询成交记录 ({start.date()} 至 {end.date()})...")
        trades = await client.list_trades(settings.TIGER_ACCOUNT, start, end)
        print(f"✓ 成交记录数量: {len(trades)}")

        if trades:
            for trade in trades[:5]:
                print(
                    f"  - {trade.timestamp.strftime('%Y-%m-%d %H:%M')} "
                    f"{trade.side} {trade.symbol} "
                    f"{trade.quantity} @ ${trade.price:.2f}"
                )

        print("\n✓ 历史成交客户端测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 历史成交客户端测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def check_config() -> bool:
    """检查配置"""
    print("=" * 60)
    print("检查配置")
    print("=" * 60)

    print(f"应用名称: {settings.APP_NAME}")
    print(f"交易模式: {settings.TRADE_MODE}")
    print(f"Tiger 账户: {settings.TIGER_ACCOUNT}")
    print(f"Tiger 私钥路径: {settings.TIGER_PRIVATE_KEY_PATH or '未配置（使用 Dummy 客户端）'}")
    print(f"Tiger ID: {settings.TIGER_ID or '未配置（使用 Dummy 客户端）'}")

    if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
        key_path = Path(settings.TIGER_PRIVATE_KEY_PATH)
        if key_path.exists():
            print(f"✓ 私钥文件存在: {key_path}")
        else:
            print(f"✗ 私钥文件不存在: {key_path}")
            return False
    else:
        print("\n⚠️  未配置 Tiger API，将使用 Dummy 客户端（测试模式）")
        print("   如需连接真实 API，请配置根目录 .env 文件中的:")
        print("   - TIGER_PRIVATE_KEY_PATH")
        print("   - TIGER_ID")

    print("\n✓ 配置检查完成")
    return True


async def main() -> bool:
    """主测试流程"""
    print("\n🚀 Tiger Open API 连接测试\n")

    if not check_config():
        print("\n❌ 配置检查失败，请检查 .env 文件")
        return False

    option_ok = await test_option_client()
    history_ok = await test_history_client()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"期权客户端: {'✓ 通过' if option_ok else '✗ 失败'}")
    print(f"历史成交客户端: {'✓ 通过' if history_ok else '✗ 失败'}")

    if option_ok and history_ok:
        print("\n✅ 所有测试通过！系统可以正常运行。")
        return True

    print("\n⚠️  部分测试失败，请检查配置和网络连接。")
    return False


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
