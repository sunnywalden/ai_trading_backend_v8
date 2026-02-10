"""
V9 演示数据初始化脚本
生成模拟的交易日志、资金曲线、价格告警等数据，用于功能演示
"""
import asyncio
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from app.models.db import SessionLocal
from app.models.equity_snapshot import EquitySnapshot
from app.models.trade_journal import TradeJournal
from app.models.price_alert import PriceAlert, AlertHistory
from app.models.trading_plan import TradingPlan
from app.broker.factory import make_option_broker_client


DEMO_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "META", "AMZN", "NIO", "BABA", "JD"]
DEMO_EMOTIONS = ["calm", "fomo", "revenge", "confident", "anxious"]
DEMO_STRATEGIES = ["momentum", "mean_reversion", "breakout", "value", "growth"]


async def init_equity_snapshots(session, account_id: str, days: int = 30):
    """生成资金曲线快照（过去N天）"""
    print(f"[EquitySnapshots] 生成过去 {days} 天的权益快照...")
    
    base_equity = 100000.0  # 初始账户 10万美元
    current_equity = base_equity
    max_equity = base_equity
    
    today = date.today()
    for i in range(days, -1, -1):
        snapshot_date = today - timedelta(days=i)
        
        # 检查是否已存在
        stmt = select(EquitySnapshot).where(
            EquitySnapshot.account_id == account_id,
            EquitySnapshot.snapshot_date == snapshot_date
        )
        result = await session.execute(stmt)
        if result.scalars().first():
            continue
        
        # 模拟每日波动 (-2% ~ +3%)
        daily_return = random.uniform(-0.02, 0.03)
        current_equity = current_equity * (1 + daily_return)
        max_equity = max(max_equity, current_equity)
        
        # 计算回撤
        drawdown_pct = (max_equity - current_equity) / max_equity if max_equity > 0 else 0
        
        # 模拟现金和市值
        cash_ratio = random.uniform(0.1, 0.3)
        cash = current_equity * cash_ratio
        market_value = current_equity - cash
        
        # 累计收益率
        cumulative_return = (current_equity - base_equity) / base_equity
        
        snapshot = EquitySnapshot(
            account_id=account_id,
            snapshot_date=snapshot_date,
            total_equity=Decimal(str(round(current_equity, 2))),
            cash=Decimal(str(round(cash, 2))),
            market_value=Decimal(str(round(market_value, 2))),
            realized_pnl=Decimal(str(round(current_equity - base_equity - market_value, 2))),
            unrealized_pnl=Decimal(str(round(market_value * 0.05, 2))),
            daily_return=Decimal(str(round(daily_return, 6))),
            cumulative_return=Decimal(str(round(cumulative_return, 6))),
            max_drawdown_pct=Decimal(str(round(drawdown_pct, 6))),
            benchmark_return=Decimal(str(round(random.uniform(-0.01, 0.02), 6))),
        )
        session.add(snapshot)
    
    await session.commit()
    print(f"[EquitySnapshots] ✅ 生成 {days + 1} 天快照完成")


async def init_trade_journals(session, account_id: str, count: int = 20):
    """生成交易日志（包含盈利和亏损的）"""
    print(f"[TradeJournal] 生成 {count} 条交易日志...")
    
    today = date.today()
    for i in range(count):
        entry_date = today - timedelta(days=random.randint(1, 60))
        exit_date = entry_date + timedelta(days=random.randint(1, 10))
        
        symbol = random.choice(DEMO_SYMBOLS)
        direction = random.choice(["BUY", "SELL"])
        quantity = random.randint(10, 200)
        entry_price = round(random.uniform(50, 300), 2)
        
        # 50% 盈利，50% 亏损
        is_win = random.random() > 0.5
        exit_multiplier = random.uniform(1.01, 1.08) if is_win else random.uniform(0.92, 0.99)
        exit_price = round(entry_price * exit_multiplier, 2)
        
        realized_pnl = (exit_price - entry_price) * quantity
        if direction == "SELL":
            realized_pnl = -realized_pnl
        
        emotion = random.choice(DEMO_EMOTIONS)
        execution_quality = random.randint(2, 5)
        
        # 根据情绪和结果生成反思
        lessons = []
        if emotion in ("fomo", "revenge"):
            lessons.append("需要更好地控制情绪")
        if execution_quality <= 2:
            lessons.append("入场时机需要优化")
        if not is_win:
            lessons.append("风控执行不到位")
        
        journal = TradeJournal(
            account_id=account_id,
            symbol=symbol,
            direction=direction,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=Decimal(str(entry_price)),
            exit_price=Decimal(str(exit_price)),
            quantity=quantity,
            realized_pnl=Decimal(str(round(realized_pnl, 2))),
            emotion_state=emotion,
            execution_quality=execution_quality,
            lesson_learned="; ".join(lessons) if lessons else "执行符合预期",
            journal_status=random.choice(["COMPLETED", "REVIEWED"]),
        )
        session.add(journal)
    
    await session.commit()
    print(f"[TradeJournal] ✅ 生成 {count} 条日志完成")


async def init_trading_plans(session, account_id: str, count: int = 10):
    """生成交易计划"""
    print(f"[TradingPlan] 生成 {count} 个交易计划...")
    
    today = date.today()
    for i in range(count):
        symbol = random.choice(DEMO_SYMBOLS)
        direction = random.choice(["BUY", "SELL"])
        entry_price = round(random.uniform(80, 280), 2)
        stop_loss = round(entry_price * 0.93, 2) if direction == "BUY" else round(entry_price * 1.07, 2)
        take_profit = round(entry_price * 1.12, 2) if direction == "BUY" else round(entry_price * 0.88, 2)
        target_position = round(random.uniform(0.05, 0.25), 4)  # 5%-25% 仓位
        
        # 70% 活跃，30% 已执行
        status = "ACTIVE" if random.random() > 0.3 else "EXECUTED"
        valid_days = random.randint(3, 14)
        
        plan = TradingPlan(
            account_id=account_id,
            symbol=symbol,
            entry_price=Decimal(str(entry_price)),
            stop_loss=Decimal(str(stop_loss)),
            take_profit=Decimal(str(take_profit)),
            target_position=Decimal(str(target_position)),
            valid_until=datetime.now() + timedelta(days=valid_days),
            notes=f"{direction} {symbol} @ ${entry_price}",
            plan_status=status,
        )
        session.add(plan)
    
    await session.commit()
    print(f"[TradingPlan] ✅ 生成 {count} 个计划完成")


async def init_price_alerts(session, account_id: str, count: int = 8):
    """生成价格告警规则和历史"""
    print(f"[PriceAlert] 生成 {count} 个价格告警...")
    
    for i in range(count):
        symbol = random.choice(DEMO_SYMBOLS)
        condition_type = random.choice(["price_above", "price_below"])
        threshold = round(random.uniform(100, 400), 2)
        
        # 60% 活跃，30% 已触发，10% 暂停
        status_pool = ["ACTIVE"] * 6 + ["TRIGGERED"] * 3 + ["PAUSED"]
        status = random.choice(status_pool)
        
        alert = PriceAlert(
            account_id=account_id,
            symbol=symbol,
            condition_type=condition_type,
            threshold=Decimal(str(threshold)),
            action=random.choice(["notify", "auto_execute", "log_only"]),
            alert_status=status,
            triggered_at=datetime.now() - timedelta(hours=random.randint(1, 48)) if status == "TRIGGERED" else None,
        )
        session.add(alert)
        await session.flush()  # 确保获得 alert.id
        
        # 为已触发的告警生成历史记录
        if status == "TRIGGERED":
            history = AlertHistory(
                alert_id=alert.id,
                account_id=account_id,
                symbol=symbol,
                trigger_price=Decimal(str(round(threshold * random.uniform(0.98, 1.02), 2))),
                trigger_time=datetime.now() - timedelta(hours=random.randint(1, 48)),
                notification_sent=True,
                action_taken=random.choice(["email_sent", "position_adjusted", "logged"]),
            )
            session.add(history)
    
    await session.commit()
    print(f"[PriceAlert] ✅ 生成 {count} 个告警完成")



async def main():
    """主初始化流程"""
    print("=" * 60)
    print("V9 演示数据初始化开始...")
    print("=" * 60)
    
    # 获取账户ID
    broker = make_option_broker_client()
    try:
        account_id = await broker.get_account_id()
    except Exception as e:
        print(f"⚠️  无法获取账户ID，使用默认值: {e}")
        account_id = "demo_account"
    
    print(f"[Init] 账户ID: {account_id}\n")
    
    async with SessionLocal() as session:
        # 初始化各模块数据
        await init_equity_snapshots(session, account_id, days=30)
        await init_trade_journals(session, account_id, count=25)
        await init_trading_plans(session, account_id, count=12)
        await init_price_alerts(session, account_id, count=10)
    
    print("\n" + "=" * 60)
    print("✅ V9 演示数据初始化完成！")
    print("=" * 60)
    print("\n现在可以访问前端页面查看：")
    print("  - Dashboard: http://localhost:5173/dashboard")
    print("  - 资金曲线: http://localhost:5173/equity")
    print("  - 交易日志: http://localhost:5173/journal")
    print("  - 价格告警: http://localhost:5173/alerts")
    print("  - 交易助手: http://localhost:5173/plans")
    print()


if __name__ == "__main__":
    asyncio.run(main())
