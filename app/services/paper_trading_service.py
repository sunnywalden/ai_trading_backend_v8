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
from app.services.v1051_research_service import v1051_research_service

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
            if float(account.current_equity) < total_cost:
                return {"success": False, "reason": "Insufficient cash"}
            account.current_equity = float(account.current_equity) - total_cost
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
            pnl = (price - pos["avg_price"]) * sell_qty - commission - slippage
            proceeds = price * sell_qty - commission - slippage
            account.current_equity = float(account.current_equity) + proceeds
            account.realized_pnl = float(account.realized_pnl or 0.0) + pnl
            if pos["qty"] - sell_qty < 0.001:
                del positions[symbol]
            else:
                positions[symbol]["qty"] = float(positions[symbol]["qty"]) - sell_qty

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
            "trade_id": str(datetime.now().timestamp()),
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "filled_price": price,
            "commission": commission,
            "slippage": slippage,
            "net_pnl": round(pnl, 2),
            "account_equity": round(float(account.current_equity), 2),
        }

    async def get_status(self, account_id: str, db: AsyncSession) -> dict:
        """获取模拟账户状态 (V10)"""
        account = await self.get_or_create_account(account_id, db)
        positions_raw = account.positions or {}
        trade_log = account.trade_log or []

        # 转换为数组格式以便前端展示，并尝试获取实时报价
        positions_list = []
        total_market_value = 0
        
        from app.data.hub import data_hub
        for symbol, data in positions_raw.items():
            qty = data.get("qty", 0)
            avg_price = data.get("avg_price", 0)
            
            # 尝试获取当前价格
            current_price = avg_price
            try:
                quote = await data_hub.get_quote(symbol)
                if quote and quote.get("price"):
                    current_price = float(quote["price"])
            except Exception:
                pass
                
            mv = qty * current_price
            total_market_value += mv
            
            unrealized_pnl = (current_price - avg_price) * qty
            unrealized_pnl_pct = (current_price / avg_price - 1) if avg_price > 0 else 0
            
            positions_list.append({
                "symbol": symbol,
                "qty": qty,
                "avg_cost": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "market_value": round(mv, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 4)
            })

        cash = float(account.current_equity)
        equity = cash + total_market_value
        initial = float(account.initial_capital)
        total_pnl = equity - initial
        total_pnl_pct = total_pnl / initial if initial > 0 else 0

        return {
            "account_id": account_id,
            "initial_capital": initial,
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "positions": positions_list,
            "trade_count": len(trade_log),
            "created_at": datetime.now(timezone.utc).isoformat()
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
            account = await self.get_or_create_account(account_id, db)
            resolved_symbols = self._resolve_graduation_symbols(
                account,
                symbols,
                max_symbols=settings.PAPER_GRADUATION_MAX_SYMBOLS,
            )
            if not resolved_symbols:
                return {
                    "eligible": False,
                    "strategy": strategy_name,
                    "metrics": {},
                    "governance_gate": self._build_governance_gate({}),
                    "criteria": {
                        "sharpe_required": 1.0,
                        "max_drawdown_limit": 0.20,
                        "win_rate_required": 0.50,
                    },
                    "message": "暂无 paper 真实交易/持仓符号，暂不执行毕业评估",
                }

            if len(resolved_symbols) < len(symbols):
                logger.info(
                    "[paper_graduation] Account %s graduation symbols narrowed from %s to %s: %s",
                    account_id,
                    len(symbols),
                    len(resolved_symbols),
                    resolved_symbols,
                )

            result = await backtest_runner.run(
                strategy_name=strategy_name,
                symbols=resolved_symbols,
                start=start,
                end=end,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
            )
            eligible = result.get("graduation_eligible", False)
            governance_gate = self._build_governance_gate(result)
            if settings.GOVERNANCE_HARD_GATE_ENABLED:
                eligible = eligible and governance_gate["eligible"]

            return {
                "eligible": eligible,
                "strategy": strategy_name,
                "metrics": result,
                "governance_gate": governance_gate,
                "criteria": {
                    "sharpe_required": 1.0,
                    "max_drawdown_limit": 0.20,
                    "win_rate_required": 0.50,
                },
                "message": (
                    "满足毕业条件，建议升级至实盘"
                    if eligible
                    else "暂未满足毕业条件，继续验证"
                ),
            }
        except Exception as e:
            return {"eligible": False, "error": str(e)}

    @staticmethod
    def _resolve_graduation_symbols(
        account: PaperAccount,
        candidate_symbols: list[str],
        max_symbols: int,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def _add(symbol: object) -> None:
            value = str(symbol or "").strip().upper()
            if not value or value in seen:
                return
            seen.add(value)
            ordered.append(value)

        positions = account.positions or {}
        for symbol in positions.keys():
            _add(symbol)

        trade_log = account.trade_log or []
        for entry in reversed(trade_log):
            _add(entry.get("symbol"))

        if candidate_symbols and not ordered:
            logger.info(
                "[paper_graduation] Skip candidate-only graduation universe: account has no real paper positions/trades, candidates=%s",
                len(candidate_symbols),
            )

        if max_symbols <= 0:
            return ordered
        return ordered[:max_symbols]

    @staticmethod
    def _build_governance_gate(result: dict) -> dict:
        sample_size = int(result.get("total_trades", 0) or 0)
        hit_rate = float(result.get("win_rate", 0.0) or 0.0)
        status = "SUCCESS" if result.get("graduation_eligible") else "FAILED"
        avg_signal_strength = float(result.get("sharpe", 0.0) or 0.0)

        compute_stage = getattr(
            v1051_research_service,
            "_compute_governance_stage",
        )
        build_evidence = getattr(
            v1051_research_service,
            "_build_governance_evidence",
        )
        build_blockers = getattr(
            v1051_research_service,
            "_build_governance_blockers",
        )
        build_rollback = getattr(
            v1051_research_service,
            "_build_rollback_suggestion",
        )

        stage = compute_stage(False, status, hit_rate, sample_size)
        evidence_chain = build_evidence(
            active=False,
            last_status=status,
            sample_size=sample_size,
            hit_rate=hit_rate,
            avg_signal_strength=avg_signal_strength,
        )
        blockers = build_blockers(evidence_chain, hit_rate, status)
        eligible = stage in {"CHALLENGER", "PRODUCTION"} and not blockers

        return {
            "gate_applied": bool(settings.GOVERNANCE_HARD_GATE_ENABLED),
            "stage": stage,
            "eligible": eligible,
            "evidence_chain": evidence_chain,
            "promotion_blockers": blockers,
            "rollback_suggestion": build_rollback(stage, blockers),
        }

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
