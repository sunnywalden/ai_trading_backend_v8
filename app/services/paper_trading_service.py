"""V10: PaperTradingService — 模拟交易服务"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.engine.backtest.runner import backtest_runner
from app.models.paper_account import PaperAccount

logger = logging.getLogger(__name__)


class PaperTradingService:
    """
    模拟交易：
    - 与实盘 AI 自主引擎共用同一信号源，但订单发送到模拟账户
    - 追踪策略 30 天验证期，自动评估是否满足 Paper→Live 毕业条件
    - Sharpe≥1.0 + MaxDrawdown≤20% + WinRate≥50% → 建议升级 Live
    """

    async def get_or_create_account(self, account_id: str, db: AsyncSession) -> PaperAccount:
        result = await db.execute(
            select(PaperAccount).where(PaperAccount.account_id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            account = PaperAccount(
                account_id=account_id,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                current_equity=settings.PAPER_INITIAL_CAPITAL,
                positions={},
                trade_log=[],
            )
            db.add(account)
            await db.flush()
        return account

    async def execute_paper_trade(
        self,
        account_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        db: AsyncSession,
    ) -> dict:
        """执行模拟交易"""
        account = await self.get_or_create_account(account_id, db)
        positions = account.positions or {}
        trade_log = account.trade_log or []

        commission = price * qty * settings.BACKTEST_COMMISSION_PCT
        slippage = price * qty * settings.BACKTEST_SLIPPAGE_PCT

        if side.upper() == "BUY":
            total_cost = price * qty + commission + slippage
            if account.current_equity < total_cost:
                return {"success": False, "reason": "Insufficient cash"}
            account.current_equity -= total_cost
            if symbol in positions:
                old_qty = positions[symbol]["qty"]
                old_avg = positions[symbol]["avg_price"]
                new_qty = old_qty + qty
                new_avg = (old_avg * old_qty + price * qty) / new_qty
                positions[symbol] = {"qty": new_qty, "avg_price": new_avg}
            else:
                positions[symbol] = {"qty": qty, "avg_price": price}
            pnl = 0.0
        else:
            if symbol not in positions:
                return {"success": False, "reason": f"No position in {symbol}"}
            pos = positions[symbol]
            sell_qty = min(qty, pos["qty"])
            proceeds = price * sell_qty - commission - slippage
            pnl = (price - pos["avg_price"]) * sell_qty - commission - slippage
            account.current_equity += proceeds
            account.realized_pnl = float(account.realized_pnl or 0) + pnl
            if pos["qty"] - sell_qty < 0.001:
                del positions[symbol]
            else:
                positions[symbol]["qty"] -= sell_qty

        # 记录成交
        trade_entry = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "pnl": round(pnl, 2),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        trade_log.append(trade_entry)
        # 保留最近 500 条
        trade_log = trade_log[-500:]

        account.positions = positions
        account.trade_log = trade_log
        await db.commit()

        return {
            "success": True,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "pnl": round(pnl, 2),
            "equity": round(float(account.current_equity), 2),
        }

    async def get_status(self, account_id: str, db: AsyncSession) -> dict:
        """获取模拟账户状态"""
        account = await self.get_or_create_account(account_id, db)
        positions = account.positions or {}
        trade_log = account.trade_log or []

        total_return = (float(account.current_equity) - settings.PAPER_INITIAL_CAPITAL) / settings.PAPER_INITIAL_CAPITAL

        return {
            "account_id": account_id,
            "initial_capital": settings.PAPER_INITIAL_CAPITAL,
            "current_equity": round(float(account.current_equity), 2),
            "realized_pnl": round(float(account.realized_pnl or 0), 2),
            "total_return_pct": round(total_return, 4),
            "positions": positions,
            "trade_count": len(trade_log),
            "recent_trades": trade_log[-10:],
        }

    async def check_graduation(
        self,
        account_id: str,
        strategy_name: str,
        symbols: list,
        db: AsyncSession,
    ) -> dict:
        """检查策略是否满足 Paper→Live 毕业条件"""
        from datetime import date, timedelta

        end = date.today()
        start = end - timedelta(days=30)

        try:
            result = await backtest_runner.run(
                strategy_name=strategy_name,
                symbols=symbols,
                start=start,
                end=end,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
            )
            eligible = result.get("graduation_eligible", False)
            return {
                "eligible": eligible,
                "strategy": strategy_name,
                "metrics": result,
                "criteria": {
                    "sharpe_required": 1.0,
                    "max_drawdown_limit": 0.20,
                    "win_rate_required": 0.50,
                },
                "message": "满足毕业条件，建议升级至实盘" if eligible else "暂未满足毕业条件，继续验证",
            }
        except Exception as e:
            return {"eligible": False, "error": str(e)}

    async def reset(self, account_id: str, db: AsyncSession) -> dict:
        """重置模拟账户"""
        from sqlalchemy import update

        await db.execute(
            update(PaperAccount)
            .where(PaperAccount.account_id == account_id)
            .values(
                current_equity=settings.PAPER_INITIAL_CAPITAL,
                realized_pnl=0,
                unrealized_pnl=0,
                positions={},
                trade_log=[],
                reset_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return {"success": True, "message": "模拟账户已重置"}


# 全局单例
paper_trading_service = PaperTradingService()
