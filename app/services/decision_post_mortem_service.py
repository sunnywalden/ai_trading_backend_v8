"""decision_post_mortem_service.py — V10.3.3 决策事后剖析服务

触发时机：仓位 position_status = CLOSED 时（由 lifecycle/broker sync 调用）
AI 模型：deepseek-reasoner（深层推理）
输出落库：decision_post_mortems 表
副作用：自动生成 source=POST_MORTEM 的 AIInsight（LESSON 类型）
"""

from __future__ import annotations

import ast
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import get_session_ctx
from app.models.decision_post_mortem import DecisionPostMortem
from app.models.trade_journal import TradeJournal

logger = logging.getLogger(__name__)

PM_MODEL = "deepseek-reasoner"
_FAILED_SUMMARY_PREFIX = "Auto-analysis failed:"
_FAILED_LESSONS_TEXT = "Analysis generation failed. Review manually."


class DecisionPostMortemService:
    """平仓后 AI 反事实剖析。"""

    @staticmethod
    def _should_regenerate(pm: DecisionPostMortem | None) -> bool:
        if pm is None:
            return False
        if (pm.status or "").lower() == "failed":
            return True
        factual_summary = (pm.factual_summary or "").strip().lower()
        key_lessons = (pm.key_lessons or "").strip().lower()
        return (
            factual_summary.startswith(_FAILED_SUMMARY_PREFIX.lower())
            or key_lessons == _FAILED_LESSONS_TEXT.lower()
        )

    @staticmethod
    def _result_indicates_failure(result: dict[str, Any] | None) -> bool:
        if not result:
            return True
        factual_summary = str(result.get("factual_summary") or "").strip().lower()
        key_lessons = str(result.get("key_lessons") or "").strip().lower()
        return (
            factual_summary.startswith(_FAILED_SUMMARY_PREFIX.lower())
            or key_lessons == _FAILED_LESSONS_TEXT.lower()
        )

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _truncate(value: Any, limit: int, default: str = "") -> str:
        text = str(value or default).strip()
        return text[:limit] if text else default

    @staticmethod
    def _normalize_label(value: Any, limit: int, default: str = "unknown") -> str:
        raw = str(value or "").strip()
        if not raw:
            return default
        lowered = raw.lower()
        if lowered.startswith("primary error category") or lowered.startswith(
            "primary cognitive bias"
        ):
            return default
        normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
        if not normalized:
            normalized = default
        return normalized[:limit]

    @classmethod
    def _normalize_tags(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value[:12]:
            label = cls._normalize_label(item, 32, default="")
            if label and label not in out:
                out.append(label)
        return out

    @classmethod
    def _apply_result(cls, pm: DecisionPostMortem, result: dict[str, Any]) -> None:
        pm.factual_summary = cls._normalize_text(result.get("factual_summary"))
        pm.counterfactual_buy = cls._normalize_text(result.get("counterfactual_buy"))
        pm.counterfactual_hold = cls._normalize_text(result.get("counterfactual_hold"))
        pm.counterfactual_sell = cls._normalize_text(result.get("counterfactual_sell"))
        pm.key_lessons = cls._normalize_text(result.get("key_lessons"))
        pm.improvement_suggestions = cls._normalize_text(
            result.get("improvement_suggestions")
        )
        pm.pattern_tags = cls._normalize_tags(result.get("pattern_tags"))
        pm.error_category = cls._normalize_label(result.get("error_category"), 64)
        pm.cognitive_bias = cls._normalize_label(result.get("cognitive_bias"), 64)
        pm.reasoning_tokens = int(result.get("reasoning_tokens") or 0)
        pm.generation_latency_ms = int(result.get("latency_ms") or 0)

    @classmethod
    def _apply_failure(
        cls, pm: DecisionPostMortem, error: Any, latency_ms: int = 0
    ) -> None:
        summary = cls._truncate(
            f"{_FAILED_SUMMARY_PREFIX} {error}", 4000, default=_FAILED_SUMMARY_PREFIX
        )
        pm.factual_summary = summary
        pm.counterfactual_buy = ""
        pm.counterfactual_hold = ""
        pm.counterfactual_sell = ""
        pm.key_lessons = _FAILED_LESSONS_TEXT
        pm.improvement_suggestions = ""
        pm.pattern_tags = []
        pm.error_category = "unknown"
        pm.cognitive_bias = "unknown"
        pm.reasoning_tokens = 0
        pm.generation_latency_ms = latency_ms
        pm.insight_id = None
        pm.status = "failed"

    @staticmethod
    async def _mark_background_failure(pm_id: int, error: Any) -> None:
        async with get_session_ctx() as db:
            pm = await db.get(DecisionPostMortem, pm_id)
            if not pm:
                return
            DecisionPostMortemService._apply_failure(pm, error)
            await db.commit()

    async def request_post_mortem(
        self,
        db: AsyncSession,
        account_id: str,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
    ) -> tuple[DecisionPostMortem, bool]:
        existing = await self._get_by_trade_id(db, trade_id)
        if existing:
            if (existing.status or "").lower() in {"pending", "running"}:
                logger.info(
                    "PostMortem: request already running for trade_id=%s", trade_id
                )
                return existing, False
            if self._should_regenerate(existing):
                logger.info(
                    "PostMortem: regenerating stale/failed record for trade_id=%s",
                    trade_id,
                )
                pm = existing
                pm.status = "running"
                pm.model_used = PM_MODEL
                pm.account_id = account_id
                pm.symbol = symbol
                pm.direction = direction
                pm.entry_price = entry_price
                pm.exit_price = exit_price
                pm.realized_pnl = realized_pnl
                pm.hold_days = hold_days
                pm.factual_summary = None
                pm.counterfactual_buy = None
                pm.counterfactual_hold = None
                pm.counterfactual_sell = None
                pm.key_lessons = None
                pm.improvement_suggestions = None
                pm.pattern_tags = None
                pm.error_category = None
                pm.cognitive_bias = None
                pm.reasoning_tokens = None
                pm.generation_latency_ms = None
                pm.insight_id = None
                await db.flush()
                return pm, True
            logger.info("PostMortem: already exists for trade_id=%s", trade_id)
            return existing, False

        pm = DecisionPostMortem(
            account_id=account_id,
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
        return pm, True

    async def generate_post_mortem(
        self,
        db: AsyncSession,
        account_id: str,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
        trade_context: dict | None = None,
    ) -> DecisionPostMortem:
        """同步主入口：兼容旧调用，但内部仍复用新的申请+执行逻辑。"""
        pm, should_queue = await self.request_post_mortem(
            db=db,
            account_id=account_id,
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            hold_days=hold_days,
        )
        if not should_queue:
            return pm

        await self.process_post_mortem(
            db=db,
            pm_id=pm.id,
            account_id=account_id,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            hold_days=hold_days,
            trade_context=trade_context or {},
        )
        await db.refresh(pm)
        return pm

    async def process_post_mortem(
        self,
        db: AsyncSession,
        pm_id: int,
        account_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
        trade_context: dict | None = None,
    ) -> DecisionPostMortem | None:
        pm = await db.get(DecisionPostMortem, pm_id)
        if not pm:
            return None

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
            if self._result_indicates_failure(result):
                self._apply_failure(
                    pm,
                    result.get("factual_summary")
                    or result.get("key_lessons")
                    or "unknown error",
                    latency_ms=int(result.get("latency_ms") or 0),
                )
                await db.flush()
                return pm
            self._apply_result(pm, result)
            pm.status = "completed"

            # 自动生成 LESSON Insight
            insight_id = await self._create_lesson_insight(
                db,
                account_id,
                symbol,
                pm.key_lessons or "",
                pm.improvement_suggestions or "",
            )
            pm.insight_id = insight_id
        except Exception as e:
            logger.error(
                "PostMortem: generation failed for trade=%s: %s",
                pm.trade_id,
                e,
            )
            self._apply_failure(pm, e)

        await db.flush()
        return pm

    async def enqueue_post_mortem_generation(
        self,
        pm_id: int,
        account_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        realized_pnl: float,
        hold_days: int,
        trade_context: dict | None = None,
    ) -> None:
        try:
            async with get_session_ctx() as db:
                await self.process_post_mortem(
                    db=db,
                    pm_id=pm_id,
                    account_id=account_id,
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    realized_pnl=realized_pnl,
                    hold_days=hold_days,
                    trade_context=trade_context or {},
                )
                await db.commit()
        except Exception as exc:
            logger.exception(
                "PostMortem background generation failed for pm_id=%s: %s", pm_id, exc
            )
            await self._mark_background_failure(pm_id, exc)

    async def get_post_mortems(
        self, db: AsyncSession, account_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        stmt = (
            select(DecisionPostMortem)
            .where(DecisionPostMortem.account_id == account_id)
            .order_by(desc(DecisionPostMortem.created_at))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_pm_to_dict(r) for r in rows]

    async def get_by_trade_id(
        self, db: AsyncSession, account_id: str, trade_id: str
    ) -> dict[str, Any] | None:
        pm = await self._get_by_trade_id(db, trade_id)
        if pm and pm.account_id == account_id:
            return _pm_to_dict(pm)
        return None

    async def get_patterns(
        self, db: AsyncSession, account_id: str, days: int = 90
    ) -> dict[str, Any]:
        """汇总常见错误模式和认知偏见。"""
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        stmt = (
            select(
                DecisionPostMortem.error_category,
                DecisionPostMortem.cognitive_bias,
                func.count().label("cnt"),
            )
            .where(
                DecisionPostMortem.account_id == account_id,
                DecisionPostMortem.created_at >= cutoff,
                DecisionPostMortem.status == "completed",
            )
            .group_by(
                DecisionPostMortem.error_category, DecisionPostMortem.cognitive_bias
            )
            .order_by(desc("cnt"))
        )
        rows = (await db.execute(stmt)).all()

        error_categories: dict[str, int] = {}
        cognitive_biases: dict[str, int] = {}
        for r in rows:
            if r.error_category:
                error_categories[r.error_category] = (
                    error_categories.get(r.error_category, 0) + r.cnt
                )
            if r.cognitive_bias:
                cognitive_biases[r.cognitive_bias] = (
                    cognitive_biases.get(r.cognitive_bias, 0) + r.cnt
                )

        # 聚合 pattern_tags
        tag_counts: dict[str, int] = {}
        tag_stmt = select(DecisionPostMortem.pattern_tags).where(
            DecisionPostMortem.account_id == account_id,
            DecisionPostMortem.created_at >= cutoff,
            DecisionPostMortem.pattern_tags.isnot(None),
        )
        tag_rows = (await db.execute(tag_stmt)).scalars().all()
        for tags in tag_rows:
            if tags:
                for tag in tags if isinstance(tags, list) else []:
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
        account_id: str,
        limit: int = 100,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回可用于生成事后剖析的交易候选（优先 trade_journal 已平仓记录）。"""
        # 当前用户已生成过剖析的 trade_id，避免重复
        existing_stmt = select(DecisionPostMortem.trade_id).where(
            DecisionPostMortem.account_id == account_id
        )
        existing_trade_ids = set((await db.execute(existing_stmt)).scalars().all())

        # 优先按当前 account_id/account_id 查询，避免多用户混淆
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

        keyword = (q or "").strip().upper()
        local_filters = [
            TradeJournal.account_id == account_id,
            TradeJournal.symbol.isnot(None),
            closed_predicate,
        ]
        if keyword:
            local_filters.append(func.upper(TradeJournal.symbol).like(f"%{keyword}%"))

        stmt = (
            select(TradeJournal)
            .where(*local_filters)
            .order_by(desc(TradeJournal.created_at))
            .limit(max(limit * 5, limit))
        )
        rows = (await db.execute(stmt)).scalars().all()

        # 兼容历史环境：若 account_id 与登录用户不一致（如 admin / sunnywalden），回退全局闭环样本
        if not rows:
            fallback_filters = [
                TradeJournal.symbol.isnot(None),
                closed_predicate,
            ]
            if keyword:
                fallback_filters.append(
                    func.upper(TradeJournal.symbol).like(f"%{keyword}%")
                )

            fallback_stmt = (
                select(TradeJournal)
                .where(*fallback_filters)
                .order_by(desc(TradeJournal.created_at))
                .limit(max(limit * 5, limit))
            )
            rows = (await db.execute(fallback_stmt)).scalars().all()
            logger.warning(
                "PostMortem: no candidates for user=%s by account_id, fallback to global closed journals, count=%d",
                account_id,
                len(rows),
            )

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
            if (
                realized_raw is None
                and entry_price > 0
                and exit_price > 0
                and quantity > 0
            ):
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
            account_id,
            (q or "").strip(),
            len(out),
        )
        return out

    async def get_trade_prefill(
        self,
        db: AsyncSession,
        account_id: str,
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
            "account_id": account_id,
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

        pnl_pct = (
            ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        )
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
                    {
                        "role": "system",
                        "content": "You are a rigorous quantitative trading post-mortem analyst. Always respond in the exact JSON format requested.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            content = resp.get("content", "{}")
            latency_ms = int((time.time() - t_start) * 1000)
            reasoning_tokens = resp.get("usage", {}).get("completion_tokens", 0)

            parsed = self._parse_reasoner_payload(content)
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

    def _parse_reasoner_payload(self, content: Any) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise ValueError("empty AI response")

        candidates: list[str] = []

        fenced_blocks = re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE
        )
        candidates.extend(block for block in fenced_blocks if block)

        brace_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if brace_match:
            candidates.append(brace_match.group(0))

        candidates.append(text)

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception as exc:
                last_error = exc
                try:
                    parsed = ast.literal_eval(candidate)
                except Exception as literal_exc:
                    last_error = literal_exc
                    continue
            if isinstance(parsed, dict):
                return parsed

        raise ValueError(f"unable to parse AI JSON payload: {last_error}")

    async def _create_lesson_insight(
        self,
        db: AsyncSession,
        account_id: str,
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
                evidence=(
                    improvement_suggestions[:1000] if improvement_suggestions else ""
                ),
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
    raw = str(v or "").strip().upper()
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
