"""V10: CopilotService — 对话式 AI 助理（Trading Copilot）"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.models.trading_plan import TradingPlan

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

    async def _resolve_context_account_id(self, account_id: str) -> str:
        """将登录用户标识解析为真实 broker account_id。"""
        try:
            from app.broker.factory import make_option_broker_client

            broker = make_option_broker_client()
            real_account_id = await broker.get_account_id()
            return str(real_account_id or account_id)
        except Exception as exc:
            logger.debug(
                "Copilot broker account resolve failed for %s: %s",
                account_id,
                exc,
            )
            return account_id

    def _build_morning_brief_fallback(
        self,
        context: dict[str, Any],
        market_regime: str,
        raw_response: str,
    ) -> dict[str, Any]:
        positions_count = int(context.get("positions_count") or 0)
        positions_preview = context.get("positions_preview") or []
        pnl_info = context.get("pnl_ticker") or {}
        preview_symbols = [str(item.get("symbol")) for item in positions_preview[:3] if item.get("symbol")]
        symbol_text = "、".join(preview_symbols) if preview_symbols else "当前持仓"
        unrealized_pct = pnl_info.get("unrealized_pnl_pct")
        unrealized_text = (
            f"未实现盈亏约 {unrealized_pct}%"
            if unrealized_pct is not None
            else "盈亏快照待补齐"
        )

        if positions_count > 0:
            summary = (
                f"账户当前持有 {positions_count} 个标的，主要仓位包括 {symbol_text}；"
                f"{unrealized_text}。"
            )
            risk_alerts = [
                "关注持仓集中度与高波动标的回撤风险。",
                "留意盘前/盘后流动性不足导致的滑点放大。",
            ]
        else:
            summary = raw_response[:150] + "..."
            risk_alerts = []

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "market_regime": market_regime,
            "summary": summary,
            "market_outlook": "结合真实持仓与市场体制动态跟踪。",
            "portfolio_snapshot": {
                "positions_count": positions_count,
                "unrealized_pnl_pct": unrealized_pct,
                "top_contributor": None,
                "beta_exposure": None,
                "mom_exposure": None,
            },
            "key_themes": [],
            "top_signals": context.get("top_signals") or [],
            "risk_alerts": risk_alerts,
        }

    def _normalize_morning_brief_result(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        positions_count = int(context.get("positions_count") or 0)
        positions_preview = context.get("positions_preview") or []
        pnl_info = context.get("pnl_ticker") or {}
        factor_exposure = context.get("factor_exposure") or {}

        snapshot = result.get("portfolio_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
            result["portfolio_snapshot"] = snapshot

        snapshot["positions_count"] = positions_count
        if snapshot.get("unrealized_pnl_pct") is None:
            snapshot["unrealized_pnl_pct"] = pnl_info.get("unrealized_pnl_pct")
        if snapshot.get("top_contributor") is None:
            snapshot["top_contributor"] = pnl_info.get("top_contributor")
        if snapshot.get("beta_exposure") is None:
            snapshot["beta_exposure"] = factor_exposure.get("portfolio_beta")
        if snapshot.get("mom_exposure") is None:
            snapshot["mom_exposure"] = factor_exposure.get("beta_mom")

        summary = str(result.get("summary") or "")
        false_empty_markers = ("空仓", "无持仓", "持仓 0", "持仓0", "positions_count: 0")
        if positions_count > 0 and any(marker in summary for marker in false_empty_markers):
            preview_symbols = [
                str(item.get("symbol"))
                for item in positions_preview[:3]
                if item.get("symbol")
            ]
            symbol_text = "、".join(preview_symbols) if preview_symbols else "当前持仓"
            unrealized_pct = pnl_info.get("unrealized_pnl_pct")
            unrealized_text = (
                f"未实现盈亏约 {unrealized_pct}%"
                if unrealized_pct is not None
                else "盈亏快照待补齐"
            )
            result["summary"] = (
                f"账户当前持有 {positions_count} 个标的，主要仓位包括 {symbol_text}；"
                f"{unrealized_text}。"
            )

            risk_alerts = result.get("risk_alerts")
            if not isinstance(risk_alerts, list):
                risk_alerts = []
            risk_alerts = [
                item for item in risk_alerts if all(marker not in str(item) for marker in false_empty_markers)
            ]
            if not risk_alerts:
                risk_alerts = [
                    "关注持仓集中度与高波动标的回撤风险。",
                    "留意盘前/盘后流动性不足导致的滑点放大。",
                ]
            result["risk_alerts"] = risk_alerts

        if positions_count > 0 and not result.get("top_signals"):
            result["top_signals"] = context.get("top_signals") or []

        has_factor_snapshot = any(
            factor_exposure.get(key) is not None
            for key in (
                "portfolio_beta",
                "beta_market",
                "beta_hml",
                "beta_smb",
                "beta_mom",
                "beta_qmj",
            )
        )

        def _normalize_text_list(items: Any) -> list[str]:
            if not isinstance(items, list):
                return []
            return [str(item).strip() for item in items if str(item).strip()]

        key_themes = _normalize_text_list(result.get("key_themes"))
        risk_alerts = _normalize_text_list(result.get("risk_alerts"))
        missing_factor_markers = ("五因子", "因子")
        missing_words = ("缺失", "未知", "暂无", "没有", "未生成")

        if has_factor_snapshot:
            def _is_false_missing_text(text: str) -> bool:
                return any(m in text for m in missing_factor_markers) and any(
                    w in text for w in missing_words
                )

            key_themes = [item for item in key_themes if not _is_false_missing_text(item)]
            risk_alerts = [item for item in risk_alerts if not _is_false_missing_text(item)]

            max_corr = factor_exposure.get("max_pairwise_corr")
            portfolio_beta = factor_exposure.get("portfolio_beta")
            if max_corr is not None and float(max_corr) >= 0.85:
                risk_alerts.append("组合相关性偏高，需防范同涨同跌带来的集中回撤。")
            if portfolio_beta is not None and float(portfolio_beta) >= 1.2:
                risk_alerts.append("组合 Beta 偏高，市场回撤时净值波动可能被放大。")
        elif positions_count > 0:
            risk_alerts = [
                item
                for item in risk_alerts
                if not (
                    any(m in item for m in missing_factor_markers)
                    and any(w in item for w in missing_words)
                )
            ]
            risk_alerts.append("五因子快照暂未生成，当前提示基于真实持仓与盈亏数据。")

        result["key_themes"] = list(dict.fromkeys(key_themes))[:4]
        result["risk_alerts"] = list(dict.fromkeys(risk_alerts))[:4]

        return result

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
        raw_response, model_used, tokens = await self._call_ai(messages, model_type, caller="copilot_chat")

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
        context_account_id = await self._resolve_context_account_id(account_id)
        cache_key = f"morning_brief:{context_account_id}:{today_str}"

        if not force_refresh:
            cached = await cache.get(cache_key)
            if cached:
                return cached

        context = await self._build_context(account_id)

        # 提取关键数据用于精简 prompt
        pnl_info = context.get("pnl_ticker") or {}
        positions_count = context.get("positions_count") or 0
        factor = context.get("factor_exposure") or {}
        signals_count = len(context.get("top_signals") or [])
        factor_info = (
            factor.get("factor_exposures")
            or factor.get("factors")
            or {"Beta": factor.get("beta", "N/A"), "MOM": factor.get("mom", "N/A")}
        )
        factor_str = json.dumps(factor_info, ensure_ascii=False)
        positions_preview_str = json.dumps(context.get("positions_preview") or [], ensure_ascii=False)
        signals_str = json.dumps(context.get("top_signals") or [], ensure_ascii=False)
        today_date = context.get("date", "YYYY-MM-DD")
        market_regime = context.get("market_regime", "UNKNOWN")

        prompt = f"""你是顶级私募量化系统专业 AI，请基于以下账户与市场快照生成今日盘前简报。

【账户快照】
- 持仓数: {positions_count}
- 未实现盈亏: {pnl_info.get('unrealized_pnl_pct', 'N/A')}%  已实现盈亏: {pnl_info.get('realized_pnl', 'N/A')}
- 市场体制: {market_regime}  自主模式: {context.get('autonomy_level', 'N/A')}
- 五因子暴露: {factor_str}
- 活跃信号数: {signals_count}
- 持仓预览: {positions_preview_str}
- 信号列表: {signals_str}

【生成要求】
1. summary: 2-3 句精炼账户状态（盈亏/仓位/主要驱动/核心风险），≤100字，风格简洁专业。
2. market_outlook: 1-2 句当日市场展望与操作建议方向，≤60字。
3. key_themes: 精选 2-4 条当日核心关注点（因子异常/集中度/机会/尾部风险等），每条≤30字。
4. portfolio_snapshot: 从数据中提取结构化指标（若数据缺失填 null）。
5. top_signals: 严格来自真实信号列表，无信号时推荐 1-2 个适合当前体制的对冲/套利标的（action 用 MONITOR_FOR_HEDGE）；禁止 A 股。
6. risk_alerts: 2-4 条具体风险提示，优先相关性集中度、单边敞口、因子异动，每条≤40字。

请严格按以下 JSON 格式输出（仅输出 JSON，不含其他文字）：
{{
  "date": "{today_date}",
  "market_regime": "{market_regime}",
  "summary": "2-3句精炼账户状态",
  "market_outlook": "市场展望与方向建议",
  "portfolio_snapshot": {{
    "positions_count": {positions_count},
    "unrealized_pnl_pct": null,
    "top_contributor": null,
    "beta_exposure": null,
    "mom_exposure": null
  }},
  "key_themes": ["关注点1", "关注点2"],
  "top_signals": [
    {{"symbol": "AAPL", "action": "BUY", "reason": "核心逻辑", "confidence": 0.75}}
  ],
  "risk_alerts": ["风险提示1", "风险提示2"]
}}"""

        messages = [{"role": "user", "content": prompt}]
        # 优化：早间简报优先保证响应速度，使用 lightweight 模型 (deepseek-chat)
        # 强制刷新也不需要 complex 推理，仅是为了获取最新数据快照
        model_type = "lightweight"
        raw_response, _, _ = await self._call_ai(messages, model_type, caller="copilot_morning_brief")
        
        result = None
        try:
            # 简单提取 JSON
            match = re.search(r"(\{.*\})", raw_response, re.DOTALL)
            if match:
                result = json.loads(match.group(1))
            else:
                result = self._build_morning_brief_fallback(
                    context,
                    market_regime,
                    raw_response,
                )
        except Exception:
            result = self._build_morning_brief_fallback(
                context,
                market_regime,
                "解析摘要失败，请刷新重试",
            )

        result = self._normalize_morning_brief_result(result, context)

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
                        f"UPDATE {TradingPlan.__tablename__} "
                        "SET stop_loss=:p, updated_at=CURRENT_TIMESTAMP "
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
                    f"UPDATE {TradingPlan.__tablename__} "
                    "SET plan_status='CANCELLED', updated_at=CURRENT_TIMESTAMP "
                    "WHERE account_id=:a AND plan_status='ACTIVE'"
                ),
                {"a": account_id},
            )
            await db.commit()

        elif intent["type"] == "pause_autonomy":
            from app.core.runtime_config import \
                set_autonomy_level as _set_level
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
        from sqlalchemy import desc, select

        from app.core.runtime_config import get_autonomy_level as _get_level
        from app.models.db import SessionLocal
        from app.models.trading_signal import SignalStatus, TradingSignal
        from app.services.regime_classifier import regime_classifier
        from app.services.war_room_service import war_room_service

        context_account_id = await self._resolve_context_account_id(account_id)

        context = {
            "account_id": context_account_id,
            "auth_user": account_id,
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
            # 排除包含 .SZ 或 .SH 的标的，同时支持 account_id=user_id 时取用户的信号
            stmt = select(TradingSignal).where(
                (TradingSignal.account_id == context_account_id)
                | (TradingSignal.account_id == account_id)
                | (TradingSignal.user_id == account_id),
                TradingSignal.status == "VALIDATED",
                ~TradingSignal.symbol.like("%.SZ"),
                ~TradingSignal.symbol.like("%.SH"),
            ).order_by(desc(TradingSignal.confidence)).limit(5)
            
            result = await db.execute(stmt)
            signals = result.scalars().all()
            for s in signals:
                reason_text = s.notes[:50] if s.notes else "六维指标共振"
                context["top_signals"].append({
                    "symbol": s.symbol,
                    "action": str(s.signal_type),
                    "confidence": s.confidence,
                    "reason": reason_text
                })

            # 3. 持仓与五因子敞口（与战情室同源，避免 Copilot 与页面口径不一致）
            try:
                exposure = await war_room_service.get_portfolio_exposure(
                    db,
                    context_account_id,
                )
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
                context["pnl_ticker"] = await war_room_service.get_pnl_ticker(
                    db,
                    context_account_id,
                )
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

    async def _call_ai(self, messages: list, model_type: str = "lightweight", caller: str = "copilot") -> tuple[str, str, int]:
        """返回 (response_text, model_name, tokens_used)，并写入 llm_call_log 用于统计"""
        import asyncio
        import time
        import uuid

        from openai import AsyncOpenAI

        from app.services.ai_client_manager import _write_llm_call_log

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

        call_id = str(uuid.uuid4())
        start_ts = time.monotonic()
        status = "ERROR"
        error_msg: str | None = None
        content = ""
        tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1500,
            )
            content = resp.choices[0].message.content or ""
            tokens = getattr(resp.usage, "total_tokens", 0)
            prompt_tokens = getattr(resp.usage, "prompt_tokens", 0)
            completion_tokens = getattr(resp.usage, "completion_tokens", 0)
            status = "SUCCESS"
        except Exception as exc:
            status = "ERROR"
            error_msg = str(exc)[:200]
            logger.warning("[Copilot._call_ai] LLM 调用异常: %s", exc)
            raise
        finally:
            latency_ms = int((time.monotonic() - start_ts) * 1000)
            asyncio.ensure_future(
                _write_llm_call_log(
                    call_id=call_id,
                    caller=caller,
                    model=model,
                    latency_ms=latency_ms,
                    status=status,
                    degraded=False,
                    error_msg=error_msg,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )
        return content, model, int(tokens)


# 全局单例
copilot_service = CopilotService()
