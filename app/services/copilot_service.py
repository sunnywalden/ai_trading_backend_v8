"""V10: CopilotService — 对话式 AI 助理（Trading Copilot）"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cache import cache

logger = logging.getLogger(__name__)

# 操作意图关键词映射
INTENT_PATTERNS = [
    # (pattern, intent_type)
    (r"把\s*(\w+)\s*止损.*?(\d+\.?\d*)", "modify_stop"),
    (r"买[入]?\s*(\w+)\s*(\d+)\s*[股份]", "place_order"),
    (r"卖[出]?\s*(\w+)\s*(\d+)?\s*[股份]?", "place_order"),
    (r"平[仓]?\s*所有|清仓", "close_all"),
    (r"暂停\s*AI|停止自主", "pause_autonomy"),
]


class CopilotService:
    """对话式 AI，支持自然语言查询 + 操作意图识别"""

    async def chat(
        self,
        account_id: str,
        session_id: str,
        message: str,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """
        处理用户消息，返回 AI 回复
        自动路由：查询类→轻量模型，复杂/操作类→复杂模型
        """
        is_complex = self._is_complex_query(message)
        model_type = "complex" if is_complex else "lightweight"

        # 构建对话历史
        history = await self._get_history(account_id, session_id, db)
        context = await self._build_context(account_id)

        prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": prompt}]
        fact_prompt = self._build_portfolio_fact_prompt(message, context)
        if fact_prompt:
            messages.append({"role": "system", "content": fact_prompt})
        # 加入最近 10 条历史
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        # 调用 AI
        raw_response, model_used, tokens = await self._call_ai(messages, model_type)

        # 意图检测
        action_intent = self._detect_intent(message, raw_response)

        # 持久化
        if db:
            await self._save_messages(db, account_id, session_id, message, raw_response, model_used, action_intent, tokens)

        response = {
            "message": raw_response,
            "session_id": session_id,
            "model_used": model_used,
            "tokens_used": tokens,
            "action_intent": action_intent,
            "requires_confirmation": action_intent is not None,
        }
        return response

    async def morning_brief(self, account_id: str, force_refresh: bool = False) -> dict:
        """每日生成盘前摘要 (V10 structured) - 已优化性能"""
        today_str = date.today().isoformat()
        cache_key = f"morning_brief:{account_id}:{today_str}"

        if not force_refresh:
            cached = await cache.get(cache_key)
            if cached:
                return cached

        context = await self._build_context(account_id)
        prompt = f"""你是顶级私募、量化系统专业 AI，请基于以下真实市场与账户信息生成今日盘前交易摘要。

当前状态：{json.dumps(context, ensure_ascii=False, indent=2)}

注意：
1. 标的范围严格限制在【美股】和【港股】，严禁包含任何 A 股（如 .SZ 或 .SH 结尾的股票）。
2. 如果 top_signals 中有数据，请优先基于这些真实信号进行分析；如果为空，则根据已知市场趋势推荐 2-3 个主流对冲或套利标的。
3. 语气要简洁、专业、客观。

请务必按以下 JSON 格式输出：
{{
  "date": "YYYY-MM-DD",
  "summary": "概要描述",
  "market_outlook": "市场展望",
  "top_signals": [
    {{"symbol": "AAPL", "action": "BUY", "reason": "xxxxx"}}
  ],
  "risk_alerts": ["xxxxx", "xxxxx"]
}}
仅输出 JSON。"""

        messages = [{"role": "user", "content": prompt}]
        # 优化：早间简报优先保证响应速度，使用 lightweight 模型 (deepseek-chat)
        # 强制刷新也不需要 complex 推理，仅是为了获取最新数据快照
        model_type = "lightweight"
        raw_response, _, _ = await self._call_ai(messages, model_type)
        
        result = None
        try:
            # 简单提取 JSON
            match = re.search(r"(\{.*\})", raw_response, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
            else:
                result = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": raw_response[:200] + "...",
                    "market_outlook": "AI 正在分析中...",
                    "top_signals": [],
                    "risk_alerts": []
                }
        except Exception:
            result = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "summary": "解析摘要失败",
                "market_outlook": raw_response,
                "top_signals": [],
                "risk_alerts": []
            }

        # 缓存结果，有效期 4 小时
        await cache.set(cache_key, result, expire=3600 * 4)
        return result

    async def confirm_action(
        self, account_id: str, action_id: str, db: AsyncSession
    ) -> dict:
        """执行 Copilot 检测到的操作意图（须人工确认）"""
        from sqlalchemy import text

        row = await db.execute(
            text("SELECT action_intent FROM copilot_messages WHERE id=:id AND account_id=:aid"),
            {"id": int(action_id), "aid": account_id},
        )
        record = row.fetchone()
        if not record or not record[0]:
            return {"success": False, "reason": "Action not found"}

        intent = record[0] if isinstance(record[0], dict) else json.loads(record[0])

        # 根据意图类型执行
        if intent["type"] == "modify_stop":
            # 更新活跃计划的止损价
            params = intent.get("params", {})
            matched = params.get("matched", [])
            symbol = matched[0] if matched else params.get("symbol")
            price = float(matched[1]) if len(matched) > 1 else float(params.get("price", 0))
            if symbol and price > 0:
                await db.execute(
                    text(
                        "UPDATE trading_plan SET stop_loss=:p, updated_at=CURRENT_TIMESTAMP "
                        "WHERE account_id=:a AND symbol=:s AND plan_status='ACTIVE'"
                    ),
                    {"p": price, "a": account_id, "s": symbol},
                )
                await db.commit()

        elif intent["type"] == "place_order":
            # 通过 TWAP 下单
            params = intent.get("params", {})
            matched = params.get("matched", [])
            symbol = matched[0] if matched else params.get("symbol")
            quantity = float(matched[1]) if len(matched) > 1 else float(params.get("quantity", 100))
            side = params.get("side", "BUY").upper()
            if symbol:
                from app.services.twap_vwap_service import TwapVwapService
                await TwapVwapService().submit(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    algo="TWAP",
                    duration_minutes=30,
                    slices=6,
                    source="copilot",
                    account_id=account_id,
                    db=db,
                )

        elif intent["type"] == "close_all":
            # 将账户所有活跃计划标记为已取消（不直接触发真实撤单，由 OrderService 异步处理）
            await db.execute(
                text(
                    "UPDATE trading_plan SET plan_status='CANCELLED', updated_at=CURRENT_TIMESTAMP "
                    "WHERE account_id=:a AND plan_status='ACTIVE'"
                ),
                {"a": account_id},
            )
            await db.commit()

        elif intent["type"] == "pause_autonomy":
            from app.core.runtime_config import set_autonomy_level as _set_level
            await _set_level("ADVISORY")

        # 标记已确认
        await db.execute(
            text("UPDATE copilot_messages SET action_confirmed=1 WHERE id=:id"),
            {"id": int(action_id)},
        )
        await db.commit()

        return {"success": True, "action_type": intent["type"], "params": intent.get("params", {})}

    # ──────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────

    def _is_complex_query(self, message: str) -> bool:
        """判断是否需要复杂推理模型"""
        complex_keywords = ["分析", "评估", "策略", "优化", "为什么", "怎么", "建议", "风险", "回测"]
        return any(kw in message for kw in complex_keywords)

    def _detect_intent(self, user_msg: str, ai_response: str) -> Optional[dict]:
        """从用户消息检测操作意图"""
        for pattern, intent_type in INTENT_PATTERNS:
            m = re.search(pattern, user_msg)
            if m:
                groups = m.groups()
                # 范围检查：禁止 A 股操作 (SZ/SH)
                if groups and any(isinstance(g, str) and (g.upper().endswith(".SZ") or g.upper().endswith(".SH")) for g in groups):
                    logger.warning(f"Blocking A-share intent detection: {user_msg}")
                    return None
                return {"type": intent_type, "params": {"matched": groups}}
        return None

    def _is_portfolio_assessment_query(self, message: str) -> bool:
        text = (message or "").strip()
        if not text:
            return False
        keywords = [
            "持仓", "仓位", "敞口", "因子", "beta", "风险", "组合", "P&L", "盈亏", "暴露",
            "portfolio", "exposure", "position", "positions", "holding", "holdings", "pnl",
        ]
        return any(k.lower() in text.lower() for k in keywords)

    def _build_portfolio_fact_prompt(self, message: str, context: dict[str, Any]) -> Optional[str]:
        """仅在持仓评估问题时注入结构化事实，减少模型幻觉。"""
        if not self._is_portfolio_assessment_query(message):
            return None

        positions_count = int(context.get("positions_count") or 0)
        positions_preview = context.get("positions_preview") or []
        factor_exposure = context.get("factor_exposure") or {}
        pnl_ticker = context.get("pnl_ticker") or {}

        return (
            "【持仓评估事实快照（必须优先引用）】\n"
            f"- positions_count: {positions_count}\n"
            f"- positions_preview: {json.dumps(positions_preview, ensure_ascii=False)}\n"
            f"- factor_exposure: {json.dumps(factor_exposure, ensure_ascii=False)}\n"
            f"- pnl_ticker: {json.dumps(pnl_ticker, ensure_ascii=False)}\n"
            "【回答要求】\n"
            "1) 先给一句结论，再给 2-4 条基于以上字段的证据。\n"
            "2) 若 positions_count=0 或 factor_exposure 为空，只能说“当前数据源暂无快照/数据不足”，不得断言账户无持仓。\n"
            "3) 不得编造未提供的仓位数量、敞口数值或收益率。"
        )

    async def _build_context(self, account_id: str) -> dict:
        """构建增强版账户上下文摘要，为 AI 提供真实决策依据"""
        from app.core.runtime_config import get_autonomy_level as _get_level
        from app.models.db import SessionLocal
        from sqlalchemy import select, desc
        from app.services.regime_classifier import regime_classifier
        from app.services.war_room_service import war_room_service
        from app.models.trading_signal import TradingSignal, SignalStatus

        context = {
            "account_id": account_id,
            "date": date.today().isoformat(),
            "autonomy_level": await _get_level(),
            "market_regime": "UNKNOWN",
            "top_signals": [],
            "positions_count": 0,
            "positions_preview": [],
            "factor_exposure": None,
            "pnl_ticker": None,
            "data_quality": {
                "positions_source": "unknown",
                "factor_source": "unknown",
            },
        }

        async with SessionLocal() as db:
            # 1. 获取当前市场体制
            regime_data = await regime_classifier.get_current_regime(db)
            if regime_data:
                # V10.2: regime_data 现在是 MarketRegime ORM 实例而非 dict
                context["market_regime"] = regime_data.regime

            # 2. 获取高置信度信号 (限 5 条，仅限美股/港股)
            # 排除包含 .SZ 或 .SH 的标的
            stmt = select(TradingSignal).where(
                TradingSignal.account_id == account_id,
                TradingSignal.status == SignalStatus.VALIDATED,
                ~TradingSignal.symbol.like("%.SZ"),
                ~TradingSignal.symbol.like("%.SH"),
            ).order_by(desc(TradingSignal.confidence)).limit(5)
            
            result = await db.execute(stmt)
            signals = result.scalars().all()
            for s in signals:
                context["top_signals"].append({
                    "symbol": s.symbol,
                    "action": str(s.signal_type),
                    "confidence": s.confidence,
                    "reason": s.research_summary[:50] if s.research_summary else "六维指标共振"
                })

            # 3. 持仓与五因子敞口（与战情室同源，避免 Copilot 与页面口径不一致）
            try:
                exposure = await war_room_service.get_portfolio_exposure(db, account_id)
                positions = exposure.get("positions") or []
                latest_factor = exposure.get("latest_snapshot")

                context["positions_count"] = len(positions)
                context["positions_preview"] = [
                    {
                        "symbol": p.get("symbol"),
                        "direction": p.get("direction"),
                        "quantity": p.get("quantity"),
                        "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                    }
                    for p in positions[:8]
                ]
                context["factor_exposure"] = latest_factor
                context["data_quality"]["positions_source"] = "war_room"
                context["data_quality"]["factor_source"] = "risk_observability"
            except Exception as exc:
                logger.debug("Copilot context exposure load failed for %s: %s", account_id, exc)

            # 4. PnL 摘要（给模型额外校验信号）
            try:
                context["pnl_ticker"] = await war_room_service.get_pnl_ticker(db, account_id)
            except Exception as exc:
                logger.debug("Copilot context pnl load failed for %s: %s", account_id, exc)

        return context

    def _build_system_prompt(self, context: dict) -> str:
        return f"""你是 Trading Copilot，一个专业的量化交易 AI 助理。
当前账户信息：{json.dumps(context, ensure_ascii=False)}
规则：
1. 标的范围仅限【美股】和【港股】，禁止推荐或分析任何 A 股（如 .SZ 或 .SH 结尾的标的）。
2. 对查询类问题直接回答。
3. 对操作类请求（下单、止损等），先确认意图再标注"需要确认"。
4. 所有回复使用中文，简洁、专业、客观。
5. 当 positions_count 为 0 或 factor_exposure 为空时，只能表述为“当前数据源未检索到/暂无快照”，禁止下绝对结论“账户没有持仓”。
6. 回答持仓评估时，优先引用 positions_preview、pnl_ticker、factor_exposure 的真实字段；字段为空时必须明确“数据不足”。"""

    async def _get_history(self, account_id: str, session_id: str, db: Optional[AsyncSession]) -> list:
        if not db:
            return []
        from sqlalchemy import text

        result = await db.execute(
            text(
                "SELECT role, content FROM copilot_messages "
                "WHERE account_id=:aid AND session_id=:sid ORDER BY created_at LIMIT 20"
            ),
            {"aid": account_id, "sid": session_id},
        )
        return [{"role": r[0], "content": r[1]} for r in result.fetchall()]

    async def _save_messages(
        self,
        db: AsyncSession,
        account_id: str,
        session_id: str,
        user_msg: str,
        ai_msg: str,
        model_used: str,
        action_intent: Optional[dict],
        tokens: int,
    ) -> None:
        from app.models.copilot_message import CopilotMessage

        db.add(CopilotMessage(account_id=account_id, session_id=session_id, role="user", content=user_msg, model_used=model_used))
        db.add(CopilotMessage(account_id=account_id, session_id=session_id, role="assistant", content=ai_msg, model_used=model_used, action_intent=action_intent, tokens_used=tokens))
        await db.commit()

    async def _call_ai(self, messages: list, model_type: str = "lightweight") -> tuple[str, str, int]:
        """返回 (response_text, model_name, tokens_used)"""
        from openai import AsyncOpenAI

        model = settings.AI_COMPLEX_MODEL if model_type == "complex" else settings.AI_LIGHTWEIGHT_MODEL

        if settings.DEEPSEEK_API_KEY and "deepseek" in model:
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
            messages=messages,
            max_tokens=1500,
        )
        content = resp.choices[0].message.content or ""
        tokens = getattr(resp.usage, "total_tokens", 0)
        return content, model, int(tokens)


# 全局单例
copilot_service = CopilotService()
