"""V10: AutonomousEngine — AI 三级自主决策引擎"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.risk_gate_service import risk_gate_service

logger = logging.getLogger(__name__)


class AutonomousEngine:
    """
    三级自主模式：
      FULL     - AI 自动决策并立即执行，无需确认
      SEMI     - AI 自动执行，但保留 REVOKE_WINDOW_MINUTES 分钟撤单窗口（默认）
      ADVISORY - AI 仅输出建议，不自动下单
    """

    def __init__(self):
        self.is_running = True  # 默认在调度器激活时允许运行

    def pause(self):
        self.is_running = False
        logger.info("AutonomousEngine PAUSED")

    def resume(self):
        self.is_running = True
        logger.info("AutonomousEngine RESUMED")

    async def run_decision_cycle(self, account_id: str, db: AsyncSession) -> list[dict]:
        """执行一个自主决策周期"""
        if not self.is_running:
            logger.info("AutonomousEngine is paused, skipping cycle.")
            return []

        from app.core.runtime_config import get_autonomy_level as _get_level
        level = await _get_level()
        logger.info(f"Starting decision cycle for {account_id}, Level={level}")
        """
        1. 拉取待处理信号
        2. AI 推理决策
        3. RiskGate 检查
        4. 按自主级别执行/通知
        5. 写审计日志
        """
        results = []

        # 获取当日已执行交易数与亏损（简化：从审计日志查）
        daily_stats = await self._get_daily_stats(account_id, db)
        daily_trades = daily_stats.get("trades", 0)
        daily_pnl = daily_stats.get("realized_pnl", 0.0)
        current_equity = daily_stats.get("equity", 100000.0)
        current_positions = daily_stats.get("positions", {})

        # 获取待处理信号
        signals = await self._fetch_pending_signals(account_id, db)
        if not signals:
            logger.debug(f"[AutonomousEngine] No pending signals for {account_id}")
            return []

        for signal in signals:
            decision = await self._ai_decide(signal, current_positions, current_equity)
            gate = await risk_gate_service.check(
                account_id=account_id,
                symbol=decision["symbol"],
                qty=float(decision.get("qty", 0)),
                side=decision["action"],
                current_equity=current_equity,
                current_positions=current_positions,
                daily_trades_today=daily_trades,
                daily_realized_pnl=daily_pnl,
            )

            order_id: Optional[str] = None
            circuit_breaker = gate.circuit_breaker

            if gate.circuit_breaker:
                logger.critical(f"[AutonomousEngine] Circuit breaker triggered for {account_id}!")
                await self._notify_circuit_breaker(account_id, daily_pnl, current_equity)

            elif gate.passed:
                if level == "ADVISORY":
                    await self._notify_suggestion(account_id, decision)
                else:
                    order_id = await self._execute_order(account_id, decision, db)
                    daily_trades += 1
                    if level == "SEMI" and order_id:
                        await self._schedule_revoke_window(account_id, order_id)

            # 写审计日志
            await self._write_audit_log(db, account_id, level, decision, gate, order_id, circuit_breaker)

            results.append({
                "symbol": decision["symbol"],
                "action": decision["action"],
                "gate_passed": gate.passed,
                "order_id": order_id,
                "circuit_breaker": circuit_breaker,
                "reason": gate.reason,
            })

        await db.commit()
        return results

    # ──────────────────────────────────────────
    # AI 决策（调用复杂模型）
    # ──────────────────────────────────────────

    async def _ai_decide(self, signal: dict, positions: dict, equity: float) -> dict:
        """
        调用 AI 复杂推理模型，返回决策字典：
        {"action":"BUY","symbol":"AAPL","qty":50,"algo":"TWAP","confidence":0.85,"reasoning":"..."}
        """
        import json
        from app.core.config import settings as cfg

        # 构造提示词
        prompt = f"""你是顶级量化交易 AI。基于以下信号做出交易决策。

信号: {json.dumps(signal, ensure_ascii=False)}
当前持仓: {json.dumps({k: v for k, v in positions.items()}, ensure_ascii=False)}
账户净值: ${equity:,.2f}
允许标的类型: {cfg.ALLOWED_ASSET_TYPES}

请输出 JSON 格式决策:
{{
  "action": "BUY|SELL|HOLD",
  "symbol": "AAPL",
  "qty": 50,
  "algo": "TWAP|VWAP|MKT",
  "confidence": 0.85,
  "reasoning": "详细推理..."
}}

只输出 JSON，不要其他文字。"""

        try:
            decision = await self._call_ai(prompt, model_type="complex")
            if isinstance(decision, str):
                import re
                m = re.search(r"\{.*\}", decision, re.DOTALL)
                if m:
                    try:
                        decision = json.loads(m.group())
                    except Exception:
                        pass
            
            if not isinstance(decision, dict):
                return {"action": "HOLD", "symbol": signal.get("symbol", ""), "qty": 0, "confidence": 0.0, "reasoning": "Parse failed"}
                
            return decision
        except Exception as e:
            logger.error(f"AI decide failed: {e}, using HOLD fallback")
            return {"action": "HOLD", "symbol": signal.get("symbol", ""), "qty": 0, "confidence": 0.0, "reasoning": f"AI error: {e}"}

    async def _call_ai(self, prompt: str, model_type: str = "lightweight") -> Any:
        """调用 AI（轻量/复杂路由）"""
        from openai import AsyncOpenAI

        model = settings.AI_COMPLEX_MODEL if model_type == "complex" else settings.AI_LIGHTWEIGHT_MODEL

        # 优先使用 DeepSeek（若配置）
        if settings.DEEPSEEK_API_KEY and ("deepseek" in model):
            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_API_BASE,
                timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
            )
        else:
            client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            )

        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        return resp.choices[0].message.content

    # ──────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────

    async def _fetch_pending_signals(self, account_id: str, db: AsyncSession) -> list[dict]:
        """从 trading_signals 获取今日未处理信号（简化实现）"""
        from sqlalchemy import text, select
        try:
            # 获取最近 10 个 PENDING 信号
            result = await db.execute(
                text(
                    "SELECT id, symbol, strategy_name, signal_type, confidence_score "
                    "FROM trading_signals WHERE status='PENDING' AND account_id=:aid "
                    "ORDER BY created_at DESC LIMIT 10"
                ),
                {"aid": account_id},
            )
            rows = result.fetchall()
            return [{"id": r[0], "symbol": r[1], "strategy": r[2], "signal_type": r[3], "confidence": r[4]} for r in rows]
        except Exception as e:
            logger.warning(f"Failed to fetch pending signals: {e}")
            return []

    async def _execute_order(self, account_id: str, decision: dict, db: AsyncSession) -> Optional[str]:
        """通过 OrderService 执行订单"""
        try:
            from app.services.order_service import OrderService

            order_svc = OrderService(db)
            payload = {
                "symbol": decision["symbol"],
                "direction": decision["action"],
                "quantity": float(decision.get("qty", 0)),
                "order_type": decision.get("algo", "MARKET") if decision.get("algo") != "MKT" else "MARKET",
                "strategy_tag": "Autonomous"
            }
            result = await order_svc.submit_order(account_id, payload)
            return result.order_id
        except Exception as e:
            logger.error(f"Execute order failed: {e}")
            return None

    async def _schedule_revoke_window(self, account_id: str, order_id: str) -> None:
        """SEMI 模式：记录可撤单窗口（实际撤单由 /autonomy/revoke API 触发）"""
        from app.core.cache import cache

        revoke_key = f"revoke_window:{account_id}:{order_id}"
        expire_secs = settings.REVOKE_WINDOW_MINUTES * 60
        try:
            # V9/V10 cache.set uses 'expire' not 'ex' if using our wrapper
            await cache.set(revoke_key, "open", expire=expire_secs)
            logger.info(f"[AutonomousEngine] Revoke window open for order {order_id} ({expire_secs}s)")
        except Exception:
            pass  # Redis 不可用时静默处理

    async def _notify_suggestion(self, account_id: str, decision: dict) -> None:
        """ADVISORY 模式：推送建议通知（Telegram）"""
        logger.info(f"[AutonomousEngine] ADVISORY suggestion for {account_id}: {decision}")
        # TODO: 接入 telegram_service.send_message

    async def _notify_circuit_breaker(self, account_id: str, daily_pnl: float, equity: float) -> None:
        """熔断触发：推送紧急通知"""
        msg = f"⚠️ 熔断触发！账户 {account_id} 今日已亏损 ${abs(daily_pnl):,.2f}（{abs(daily_pnl)/equity:.1%}），AI 交易已暂停。"
        logger.critical(msg)
        # TODO: 接入 telegram_service.send_message

    async def _get_daily_stats(self, account_id: str, db: AsyncSession) -> dict:
        """
        获取当日统计（交易笔数、已实现盈亏、账户净值、持仓快照）。

        数据来源：
          - trades       : AutonomyAuditLog 今日已下单条数
          - realized_pnl : 今日审计日志中已执行订单（order_id 非空）的 realized_pnl 累加
          - equity       : 优先从 Broker 实时查询；失败则用最近 EquitySnapshot；再失败默认 100000
          - positions    : PositionMonitor.get_positions_snapshot()（真实仓位）
        """
        from datetime import date
        from sqlalchemy import func, select as sa_select

        result: dict = {"trades": 0, "realized_pnl": 0.0, "equity": 100000.0, "positions": {}}

        # ── 1. 审计日志：今日交易次数 ───────────────────────────────────────────
        try:
            from app.models.autonomy_audit_log import AutonomyAuditLog
            today = date.today()
            stmt = sa_select(func.count()).where(
                AutonomyAuditLog.account_id == account_id,
                AutonomyAuditLog.order_id.isnot(None),
                func.date(AutonomyAuditLog.created_at) == today,
            )
            res = await db.execute(stmt)
            result["trades"] = res.scalar() or 0
        except Exception as e:
            logger.debug(f"[AutonomousEngine] trade count query failed: {e}")

        # ── 2. 账户净值：优先 Broker 实时，再 EquitySnapshot ──────────────────
        try:
            from app.broker.factory import make_option_broker_client
            broker = make_option_broker_client()
            from app.broker.dummy_option_client import DummyOptionClient
            if not isinstance(broker, DummyOptionClient):
                account_info: Any = await broker.get_account_equity(account_id)
                if not isinstance(account_info, dict):
                    account_info = {}
                equity_val = account_info.get("net_liquidation") or account_info.get("equity")
                if equity_val:
                    result["equity"] = float(equity_val)
            else:
                raise ValueError("dummy client")
        except Exception:
            try:
                from app.models.equity_snapshot import EquitySnapshot
                snap_stmt = (
                    sa_select(EquitySnapshot)
                    .where(EquitySnapshot.account_id == account_id)
                    .order_by(EquitySnapshot.snapshot_date.desc())
                    .limit(1)
                )
                snap_res = await db.execute(snap_stmt)
                snap = snap_res.scalars().first()
                if snap and snap.total_equity:
                    result["equity"] = float(snap.total_equity)
            except Exception as e2:
                logger.debug(f"[AutonomousEngine] equity snapshot fallback failed: {e2}")

        # ── 3. 实时持仓快照 ────────────────────────────────────────────────────
        try:
            from app.engine.position_monitor import PositionMonitor
            monitor = PositionMonitor(db)
            result["positions"] = await monitor.get_positions_snapshot(account_id)
        except Exception as e:
            logger.debug(f"[AutonomousEngine] position snapshot failed: {e}")

        # ── 4. 今日已实现盈亏（从持仓快照中取浮盈作为近似；实际可接入执行记录）
        realised = 0.0
        for pos_data in result.get("positions", {}).values():
            pnl_pct = pos_data.get("unrealized_pnl_pct", 0.0)
            avg_cost = pos_data.get("avg_cost", 0.0)
            qty = pos_data.get("qty", 0.0)
            realised += pnl_pct * avg_cost * abs(qty)
        result["realized_pnl"] = round(realised, 2)

        return result

    async def _write_audit_log(
        self,
        db: AsyncSession,
        account_id: str,
        level: str,
        decision: dict,
        gate: Any,
        order_id: Optional[str],
        circuit_breaker: bool,
    ) -> None:
        from app.models.autonomy_audit_log import AutonomyAuditLog

        log = AutonomyAuditLog(
            account_id=account_id,
            autonomy_level=level,
            decision_type=decision.get("action", "UNKNOWN"),
            symbol=decision.get("symbol"),
            ai_reasoning=decision.get("reasoning"),
            confidence_score=decision.get("confidence"),
            risk_gate_passed=gate.passed,
            risk_gate_detail=gate.details,
            order_id=order_id,
            circuit_breaker_triggered=circuit_breaker,
        )
        db.add(log)

    # ──────────────────────────────────────────
    # 撤单（SEMI 模式 30 分钟窗口）
    # ──────────────────────────────────────────

    async def revoke_order(self, account_id: str, exec_id: str, reason: str, db: AsyncSession) -> dict:
        """在撤单窗口内撤销 AI 自动执行的订单"""
        from app.core.cache import cache
        from sqlalchemy import text as sql_text

        revoke_key = f"revoke_window:{account_id}:{exec_id}"
        window_open = False
        try:
            val = await cache.get(revoke_key)
            window_open = val is not None
        except Exception:
            window_open = True  # Redis 不可用时允许撤单

        if not window_open:
            return {"success": False, "reason": "Revoke window expired"}

        # 取消订单（通过 broker）
        try:
            from app.services.order_service import OrderService
            order_svc = OrderService(db)
            await order_svc.cancel_order(exec_id)
            
            # 更新审计日志
            await db.execute(
                sql_text(
                    "UPDATE autonomy_audit_log SET revoked_at=:now, revoke_reason=:reason WHERE order_id=:oid"
                ),
                {"now": datetime.now(timezone.utc), "reason": reason, "oid": exec_id}
            )
            await db.commit()
            
            try:
                await cache.delete(revoke_key)
            except Exception:
                pass
                
            return {"success": True, "message": f"Order {exec_id} revoked successfully"}
        except Exception as e:
            logger.error(f"Revoke failed: {e}")
            return {"success": False, "reason": str(e)}


# 全局单例
autonomous_engine = AutonomousEngine()
