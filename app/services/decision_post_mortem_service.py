"""decision_post_mortem_service.py — V10.3.3 决策事后剖析服务

触发时机：仓位 position_status = CLOSED 时（由 lifecycle/broker sync 调用）
AI 模型：deepseek-reasoner（深层推理）
输出落库：decision_post_mortems 表
副作用：自动生成 source=POST_MORTEM 的 AIInsight（LESSON 类型）
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_post_mortem import DecisionPostMortem
from app.models.trade_journal import TradeJournal

logger = logging.getLogger(__name__)

PM_MODEL = "deepseek-reasoner"


class DecisionPostMortemService:
    """平仓后 AI 反事实剖析。"""

    async def generate_post_mortem(
        self,
        db: AsyncSession,
        user_id: str,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
        trade_context: dict | None = None,
    ) -> DecisionPostMortem:
        """主入口：由仓位关闭事件触发。"""

        # 幂等检查
        existing = await self._get_by_trade_id(db, trade_id)
        if existing:
            logger.info("PostMortem: already exists for trade_id=%s", trade_id)
            return existing

        # 创建 pending 记录
        pm = DecisionPostMortem(
            user_id=user_id,
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            hold_days=hold_days,
            status="running",
            model_used=PM_MODEL,
        )
        db.add(pm)
        await db.flush()

        try:
            result = await self._call_deepseek_reasoner(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                hold_days=hold_days,
                context=trade_context or {},
            )
            pm.factual_summary = result.get("factual_summary", "")
            pm.counterfactual_buy = result.get("counterfactual_buy", "")
            pm.counterfactual_hold = result.get("counterfactual_hold", "")
            pm.counterfactual_sell = result.get("counterfactual_sell", "")
            pm.key_lessons = result.get("key_lessons", "")
            pm.improvement_suggestions = result.get("improvement_suggestions", "")
            pm.pattern_tags = result.get("pattern_tags", [])
            pm.error_category = result.get("error_category", "")
            pm.cognitive_bias = result.get("cognitive_bias", "")
            pm.reasoning_tokens = result.get("reasoning_tokens", 0)
            pm.generation_latency_ms = result.get("latency_ms", 0)
            pm.status = "completed"

            # 自动生成 LESSON Insight
            insight_id = await self._create_lesson_insight(
                db, user_id, symbol, pm.key_lessons or "", pm.improvement_suggestions or ""
            )
            pm.insight_id = insight_id

        except Exception as e:
            logger.error("PostMortem: generation failed for trade=%s: %s", trade_id, e)
            pm.status = "failed"

        await db.flush()
        return pm

    async def get_post_mortems(
        self, db: AsyncSession, user_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        stmt = (
            select(DecisionPostMortem)
            .where(DecisionPostMortem.user_id == user_id)
            .order_by(desc(DecisionPostMortem.created_at))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_pm_to_dict(r) for r in rows]

    async def get_by_trade_id(
        self, db: AsyncSession, user_id: str, trade_id: str
    ) -> dict[str, Any] | None:
        pm = await self._get_by_trade_id(db, trade_id)
        if pm and pm.user_id == user_id:
            return _pm_to_dict(pm)
        return None

    async def get_patterns(
        self, db: AsyncSession, user_id: str, days: int = 90
    ) -> dict[str, Any]:
        """汇总常见错误模式和认知偏见。"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                DecisionPostMortem.error_category,
                DecisionPostMortem.cognitive_bias,
                func.count().label("cnt"),
            )
            .where(
                DecisionPostMortem.user_id == user_id,
                DecisionPostMortem.created_at >= cutoff,
                DecisionPostMortem.status == "completed",
            )
            .group_by(DecisionPostMortem.error_category, DecisionPostMortem.cognitive_bias)
            .order_by(desc("cnt"))
        )
        rows = (await db.execute(stmt)).all()

        error_categories: dict[str, int] = {}
        cognitive_biases: dict[str, int] = {}
        for r in rows:
            if r.error_category:
                error_categories[r.error_category] = error_categories.get(r.error_category, 0) + r.cnt
            if r.cognitive_bias:
                cognitive_biases[r.cognitive_bias] = cognitive_biases.get(r.cognitive_bias, 0) + r.cnt

        # 聚合 pattern_tags
        tag_counts: dict[str, int] = {}
        tag_stmt = (
            select(DecisionPostMortem.pattern_tags)
            .where(
                DecisionPostMortem.user_id == user_id,
                DecisionPostMortem.created_at >= cutoff,
                DecisionPostMortem.pattern_tags.isnot(None),
            )
        )
        tag_rows = (await db.execute(tag_stmt)).scalars().all()
        for tags in tag_rows:
            if tags:
                for tag in (tags if isinstance(tags, list) else []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {
            "error_categories": sorted(error_categories.items(), key=lambda x: -x[1]),
            "cognitive_biases": sorted(cognitive_biases.items(), key=lambda x: -x[1]),
            "pattern_tags": sorted(tag_counts.items(), key=lambda x: -x[1])[:15],
            "lookback_days": days,
        }

    async def list_trade_candidates(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 100,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回可用于生成事后剖析的交易候选（优先 trade_journal 已平仓记录）。"""
        # 当前用户已生成过剖析的 trade_id，避免重复
        existing_stmt = select(DecisionPostMortem.trade_id).where(DecisionPostMortem.user_id == user_id)
        existing_trade_ids = set((await db.execute(existing_stmt)).scalars().all())

        # 优先按当前 user_id/account_id 查询，避免多用户混淆
        # 已平仓判定：
        # 1) realized_pnl 非空；或
        # 2) entry/exit 价格齐全（可推导收益）
        closed_predicate = or_(
            TradeJournal.realized_pnl.is_not(None),
            and_(
                TradeJournal.entry_price.is_not(None),
                TradeJournal.exit_price.is_not(None),
            ),
        )

        stmt = (
            select(TradeJournal)
            .where(
                TradeJournal.account_id == user_id,
                TradeJournal.symbol.isnot(None),
                closed_predicate,
            )
            .order_by(desc(TradeJournal.created_at))
            .limit(max(limit * 3, limit))
        )
        rows = (await db.execute(stmt)).scalars().all()

        # 兼容历史环境：若 account_id 与登录用户不一致（如 admin / sunnywalden），回退全局闭环样本
        if not rows:
            fallback_stmt = (
                select(TradeJournal)
                .where(
                    TradeJournal.symbol.isnot(None),
                    closed_predicate,
                )
                .order_by(desc(TradeJournal.created_at))
                .limit(max(limit * 3, limit))
            )
            rows = (await db.execute(fallback_stmt)).scalars().all()
            logger.warning(
                "PostMortem: no candidates for user=%s by account_id, fallback to global closed journals, count=%d",
                user_id,
                len(rows),
            )

        keyword = (q or "").strip().upper()
        out: list[dict[str, Any]] = []
        for r in rows:
            symbol = (getattr(r, "symbol", "") or "").upper()
            if keyword and keyword not in symbol:
                continue

            rid = int(getattr(r, "id", 0) or 0)
            trade_id = f"journal:{rid}"
            # 兼容历史写法（纯数字 trade_id）
            if trade_id in existing_trade_ids or str(rid) in existing_trade_ids:
                continue

            entry_price = _to_float(getattr(r, "entry_price", None), 0.0)
            exit_price = _to_float(getattr(r, "exit_price", None), 0.0)
            quantity = _to_float(getattr(r, "quantity", None), 0.0)
            realized_raw = getattr(r, "realized_pnl", None)
            realized = _to_float(realized_raw, 0.0)
            if realized_raw is None and entry_price > 0 and exit_price > 0 and quantity > 0:
                realized = (exit_price - entry_price) * quantity
            created_at = getattr(r, "created_at", None)
            hold_days = int(getattr(r, "holding_days", 0) or 0)

            out.append(
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "direction": _normalize_direction(getattr(r, "direction", None)),
                    "realized_pnl": realized,
                    "hold_days": hold_days,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "created_at": created_at.isoformat() if created_at else None,
                    "display": f"{symbol} | PnL {realized:+.2f} | {created_at.date() if created_at else '-'}",
                }
            )
            if len(out) >= limit:
                break

        logger.info(
            "PostMortem: list_trade_candidates user=%s q=%s returned=%d",
            user_id,
            (q or "").strip(),
            len(out),
        )
        return out

    async def get_trade_prefill(
        self,
        db: AsyncSession,
        user_id: str,
        trade_id: str,
    ) -> dict[str, Any] | None:
        """根据 trade_id 返回可用于生成剖析的预填参数。"""
        journal_id = _parse_journal_trade_id(trade_id)
        if journal_id is None:
            return None

        stmt = select(TradeJournal).where(TradeJournal.id == journal_id).limit(1)
        row = (await db.execute(stmt)).scalars().first()
        if not row:
            return None

        # 如当前用户已生成过该交易，仍允许返回预填，前端可直接打开已存在详情
        entry_price = _to_float(getattr(row, "entry_price", None), 0.0)
        exit_price = _to_float(getattr(row, "exit_price", None), 0.0)
        realized_pnl = _to_float(getattr(row, "realized_pnl", None), 0.0)
        hold_days = int(getattr(row, "holding_days", 0) or 0)
        if hold_days <= 0:
            entry_date = getattr(row, "entry_date", None)
            exit_date = getattr(row, "exit_date", None)
            if entry_date and exit_date:
                hold_days = max((exit_date - entry_date).days, 1)
            else:
                hold_days = 1

        context_parts: list[str] = []
        emotion = getattr(row, "emotion_state", None)
        if emotion:
            context_parts.append(f"emotion={emotion}")
        tags = getattr(row, "mistake_tags", None)
        if isinstance(tags, list) and tags:
            context_parts.append(f"mistake_tags={','.join(str(t) for t in tags)}")
        lesson = getattr(row, "lesson_learned", None)
        if lesson:
            context_parts.append(f"lesson={lesson}")

        return {
            "trade_id": f"journal:{int(getattr(row, 'id', 0) or 0)}",
            "symbol": (getattr(row, "symbol", "") or "").upper(),
            "direction": _normalize_direction(getattr(row, "direction", None)),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "hold_days": hold_days,
            "trade_context": " | ".join(context_parts),
            "user_id": user_id,
        }

    async def _get_by_trade_id(
        self, db: AsyncSession, trade_id: str
    ) -> DecisionPostMortem | None:
        stmt = select(DecisionPostMortem).where(DecisionPostMortem.trade_id == trade_id)
        return (await db.execute(stmt)).scalars().first()

    async def _call_deepseek_reasoner(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
        context: dict,
    ) -> dict[str, Any]:
        """调用 DeepSeek Reasoner 生成反事实分析。"""
        import time
        from app.services.ai_client import call_ai

        pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        direction_label = "bought" if direction == "BUY" else "shorted"

        prompt = f"""You are a professional quantitative trading analyst. Analyze this closed trade and provide a thorough post-mortem.

TRADE DETAILS:
- Symbol: {symbol}
- Direction: {direction} ({direction_label})
- Entry: ${entry_price:.2f} | Exit: ${exit_price:.2f}
- P&L: ${realized_pnl:.2f} ({pnl_pct:+.2f}%)
- Hold Duration: {hold_days} days
- Context: {context}

Provide your analysis in the following EXACT JSON format:
{{
  "factual_summary": "What actually happened — market context, entry/exit rationale...",
  "counterfactual_buy": "If we had maintained/initiated a larger BUY position, what would have happened?",
  "counterfactual_hold": "If we had simply held without action, outcome would have been...",
  "counterfactual_sell": "If we had sold earlier/later, outcome would have been...",
  "key_lessons": "3-5 key lessons from this trade in bullet points",
  "improvement_suggestions": "Specific improvements to entry/exit/sizing/timing",
  "pattern_tags": ["pattern1", "pattern2"],
  "error_category": "primary error category (e.g. premature_exit, chasing_momentum, etc.)",
  "cognitive_bias": "primary cognitive bias identified (e.g. loss_aversion, recency_bias, etc.)"
}}"""

        t_start = time.time()
        try:
            resp = await call_ai(
                model=PM_MODEL,
                messages=[
                    {"role": "system", "content": "You are a rigorous quantitative trading post-mortem analyst. Always respond in the exact JSON format requested."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
            )
            content = resp.get("content", "{}")
            latency_ms = int((time.time() - t_start) * 1000)
            reasoning_tokens = resp.get("usage", {}).get("completion_tokens", 0)

            # 解析 JSON
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            parsed = json.loads(content[start:end]) if start >= 0 else {}
            parsed["latency_ms"] = latency_ms
            parsed["reasoning_tokens"] = reasoning_tokens
            return parsed
        except Exception as e:
            logger.error("PostMortem AI call failed: %s", e)
            return {
                "factual_summary": f"Auto-analysis failed: {e}",
                "counterfactual_buy": "",
                "counterfactual_hold": "",
                "counterfactual_sell": "",
                "key_lessons": "Analysis generation failed. Review manually.",
                "improvement_suggestions": "",
                "pattern_tags": [],
                "error_category": "unknown",
                "cognitive_bias": "unknown",
                "latency_ms": int((time.time() - t_start) * 1000),
                "reasoning_tokens": 0,
            }

    async def _create_lesson_insight(
        self,
        db: AsyncSession,
        user_id: str,
        symbol: str,
        key_lessons: str,
        improvement_suggestions: str,
    ) -> int | None:
        """自动创建 LESSON 类型 Insight。"""
        try:
            from app.models.ai_insight import AIInsight
            insight = AIInsight(
                insight_type="LESSON",
                symbol=symbol,
                title=f"Post-mortem lesson: {symbol}",
                summary=key_lessons[:1000] if key_lessons else "",
                evidence=improvement_suggestions[:1000] if improvement_suggestions else "",
                created_by_job="post_mortem_service",
            )
            db.add(insight)
            await db.flush()
            return insight.id
        except Exception as e:
            logger.warning("PostMortem: failed to create lesson insight: %s", e)
            return None


def _pm_to_dict(pm: DecisionPostMortem) -> dict[str, Any]:
    return {
        "id": pm.id,
        "trade_id": pm.trade_id,
        "symbol": pm.symbol,
        "direction": pm.direction,
        "entry_price": pm.entry_price,
        "exit_price": pm.exit_price,
        "realized_pnl": pm.realized_pnl,
        "hold_days": pm.hold_days,
        "factual_summary": pm.factual_summary,
        "counterfactual_buy": pm.counterfactual_buy,
        "counterfactual_hold": pm.counterfactual_hold,
        "counterfactual_sell": pm.counterfactual_sell,
        "key_lessons": pm.key_lessons,
        "improvement_suggestions": pm.improvement_suggestions,
        "pattern_tags": pm.pattern_tags,
        "error_category": pm.error_category,
        "cognitive_bias": pm.cognitive_bias,
        "model_used": pm.model_used,
        "reasoning_tokens": pm.reasoning_tokens,
        "status": pm.status,
        "insight_id": pm.insight_id,
        "created_at": pm.created_at.isoformat() if pm.created_at else None,
    }


decision_post_mortem_service = DecisionPostMortemService()


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _normalize_direction(v: Any) -> str:
    raw = (str(v or "").strip().upper())
    if raw in {"BUY", "LONG", "B"}:
        return "long"
    if raw in {"SELL", "SHORT", "S"}:
        return "short"
    return "long"


def _parse_journal_trade_id(trade_id: str) -> int | None:
    raw = (trade_id or "").strip()
    if not raw:
        return None
    if raw.startswith("journal:"):
        raw = raw.split(":", 1)[1]
    try:
        val = int(raw)
        return val if val > 0 else None
    except Exception:
        return None
