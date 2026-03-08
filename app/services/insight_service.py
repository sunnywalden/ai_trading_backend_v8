"""V10.2-M6: AI 洞察服务 + 每周洞察任务

InsightService：
    - 从 ai_insight_repository 读取/写入经验规则
    - 提供 CRUD + 统计接口

WeeklyInsightGenerator：
    - 读取最近 30 天的 TradeAttributionEntry
    - 调用 deepseek-reasoner 批量分析
    - 生成 AIInsight 记录
    - 触发 INSIGHT_GENERATED 事件

ABTestEngine：
    - 创建 ABExperiment 记录
    - 监控实验进度，执行 p-value 显著性检验
    - 实验通过后自动应用新参数
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import Topics, event_bus
from app.models.ai_insight import ABExperiment, AIInsight, ExperimentStatus, InsightType

logger = logging.getLogger(__name__)

FAILED_POST_MORTEM_LESSON_SUMMARY = "Analysis generation failed. Review manually."
POST_MORTEM_CREATED_BY_JOB = "post_mortem_service"


class InsightService:
    """AI 经验库 CRUD + 统计服务"""

    async def list_insights(
        self,
        db: AsyncSession,
        insight_type: Optional[str] = None,
        regime: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AIInsight], int]:
        """分页查询洞察列表，返回 (rows, total)。"""
        from sqlalchemy import func, select

        stmt = select(AIInsight)
        stmt = stmt.where(
            not_(
                and_(
                    AIInsight.created_by_job == POST_MORTEM_CREATED_BY_JOB,
                    AIInsight.summary == FAILED_POST_MORTEM_LESSON_SUMMARY,
                )
            )
        )
        if active_only:
            stmt = stmt.where(AIInsight.active == True)  # noqa: E712
        if insight_type:
            stmt = stmt.where(AIInsight.insight_type == insight_type)
        if regime:
            stmt = stmt.where(AIInsight.regime == regime)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(total_stmt)).scalar_one_or_none() or 0

        stmt = stmt.order_by(AIInsight.confidence.desc()).limit(limit).offset(offset)
        rows = list((await db.execute(stmt)).scalars().all())
        return rows, total

    async def get_insight(
        self, db: AsyncSession, insight_id: int
    ) -> Optional[AIInsight]:
        return (
            (await db.execute(select(AIInsight).where(AIInsight.id == insight_id)))
            .scalars()
            .first()
        )

    async def create_insight(self, db: AsyncSession, data: dict) -> AIInsight:
        insight = AIInsight(**data)
        db.add(insight)
        await db.commit()
        await db.refresh(insight)
        await event_bus.publish(Topics.INSIGHT_GENERATED, insight.to_dict())
        return insight

    async def toggle_active(
        self, db: AsyncSession, insight_id: int, active: bool
    ) -> bool:
        result = await db.execute(
            update(AIInsight).where(AIInsight.id == insight_id).values(active=active)
        )
        await db.commit()
        # rowcount not defined in stub
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def record_application(
        self, db: AsyncSession, insight_id: int, success: bool
    ) -> None:
        from sqlalchemy import literal

        await db.execute(
            update(AIInsight)
            .where(AIInsight.id == insight_id)
            .values(
                applied_count=AIInsight.applied_count + 1,
                success_count=AIInsight.success_count + (1 if success else 0),
            )
        )
        await db.commit()


class WeeklyInsightGenerator:
    """
    每周洞察生成器（Sunday 22:00 由 insight_jobs 调用）。

    算法：
    1. 读取最近 30 天的 trade_attribution_entries
    2. 按 category (WIN/LOSS) 分组
    3. 构建 prompt → 调用 deepseek-reasoner
    4. 解析 JSON 响应 → 批量写入 ai_insight_repository
    """

    async def run(self, db: AsyncSession) -> list[AIInsight]:
        """执行一次洞察生成流程，返回新生成的洞察列表。"""
        logger.info("[WeeklyInsight] starting insight generation run")

        trade_data = await self._fetch_recent_trades(db)
        if not trade_data:
            logger.info("[WeeklyInsight] no trade data available, skipping")
            return []

        raw_insights = await self._call_deepseek(trade_data)
        if not raw_insights:
            logger.info(
                "[WeeklyInsight] AI generation empty, using rule-based fallback"
            )
            raw_insights = self._rule_based_insights(trade_data)
        if not raw_insights:
            return []

        created: list[AIInsight] = []
        for item in raw_insights:
            try:
                insight = AIInsight(
                    insight_type=item.get("type", InsightType.PATTERN),
                    regime=item.get("regime"),
                    symbol=item.get("symbol"),
                    title=item["title"],
                    summary=item["summary"],
                    evidence=item.get("evidence"),
                    actionable_rule=item.get("actionable_rule"),
                    confidence=float(item.get("confidence", 0.5)),
                    win_rate_impact=item.get("win_rate_impact"),
                    created_by_job="weekly_insight_job",
                )
                db.add(insight)
                await db.flush()
                created.append(insight)
                await event_bus.publish(
                    Topics.INSIGHT_GENERATED,
                    self._insight_event_payload(insight),
                )
            except Exception as e:
                logger.warning(f"[WeeklyInsight] failed to persist insight: {e}")

        await db.commit()
        # refresh to re-load all columns (commit expires ORM objects by default;
        # accessing attributes outside the async greenlet would raise MissingGreenlet)
        for ins in created:
            await db.refresh(ins)
        logger.info(f"[WeeklyInsight] generated {len(created)} new insights")
        return created

    async def _fetch_recent_trades(self, db: AsyncSession) -> list[dict]:
        """拉取最近 30 天交易样本：优先 attribution，缺失时回退 trade_journal。"""
        from sqlalchemy import select

        from app.models.trade_attribution import TradeAttributionEntry

        since = datetime.now(tz=timezone.utc) - timedelta(days=30)
        stmt = (
            select(TradeAttributionEntry)
            .where(TradeAttributionEntry.created_at >= since)
            .order_by(TradeAttributionEntry.created_at.desc())
            .limit(200)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        if rows:
            return [r.to_dict() for r in rows]

        logger.info("[WeeklyInsight] no attribution data, fallback to trade_journal")
        return await self._fetch_recent_journal_trades(db)

    async def _fetch_recent_journal_trades(self, db: AsyncSession) -> list[dict]:
        """从 trade_journal 组装洞察训练样本（兜底数据源）。"""
        from sqlalchemy import or_, select

        from app.models.trade_journal import TradeJournal

        since = datetime.now(tz=timezone.utc) - timedelta(days=30)
        since_date = since.date()

        stmt = (
            select(TradeJournal)
            .where(
                or_(
                    TradeJournal.exit_date >= since_date,
                    TradeJournal.entry_date >= since_date,
                )
            )
            .order_by(TradeJournal.updated_at.desc())
            .limit(200)
        )
        journals = list((await db.execute(stmt)).scalars().all())

        results: list[dict] = []
        for j in journals:
            entry_price = self._to_float(getattr(j, "entry_price", None))
            exit_price = self._to_float(getattr(j, "exit_price", None))
            quantity = max(self._to_float(getattr(j, "quantity", None)), 0.0)
            realized_pnl = self._to_float(getattr(j, "realized_pnl", None))

            pnl_pct = 0.0
            if entry_price > 0 and exit_price > 0:
                pnl_pct = (exit_price - entry_price) / entry_price
            elif entry_price > 0 and quantity > 0 and realized_pnl != 0:
                base = entry_price * quantity
                if base > 0:
                    pnl_pct = realized_pnl / base

            if pnl_pct > 0.005:
                category = "WIN"
            elif pnl_pct < -0.005:
                category = "LOSS"
            else:
                category = "BREAKEVEN"

            hold_days = 0
            entry_date = getattr(j, "entry_date", None)
            exit_date = getattr(j, "exit_date", None)
            if entry_date and exit_date:
                hold_days = max(0, (exit_date - entry_date).days)

            execution_quality = self._to_float(getattr(j, "execution_quality", None))
            execution_score = (
                execution_quality / 100.0
                if execution_quality > 1
                else execution_quality
            )

            results.append(
                {
                    "symbol": getattr(j, "symbol", "UNKNOWN"),
                    "pnl_pct": pnl_pct,
                    "category": category,
                    "alpha_source": "JOURNAL_FALLBACK",
                    "execution_score": execution_score if execution_score > 0 else None,
                    "position_mgmt_score": None,
                    "regime_at_entry": None,
                    "scale_in_count": 0,
                    "hold_days": hold_days,
                }
            )

        return results

    @staticmethod
    def _to_float(v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, Decimal):
            return float(v)
        try:
            return float(v)
        except Exception:
            return 0.0

    async def _call_deepseek(self, trade_data: list[dict]) -> list[dict]:
        """调用 deepseek-reasoner 生成洞察，返回 list of insight dicts。"""
        try:
            from openai import AsyncOpenAI

            from app.core.config import settings

            client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
            )

            # 压缩提示（只包含关键字段）
            summary_data = [
                {
                    "symbol": t["symbol"],
                    "pnl_pct": t["pnl_pct"],
                    "category": t["category"],
                    "alpha_source": t.get("alpha_source"),
                    "execution_score": t.get("execution_score"),
                    "position_mgmt_score": t.get("position_mgmt_score"),
                    "regime_at_entry": t.get("regime_at_entry"),
                    "scale_in_count": t.get("scale_in_count", 0),
                    "hold_days": t.get("hold_days", 0),
                }
                for t in trade_data[:100]  # 限制 token
            ]

            prompt = f"""You are a quantitative trading analyst AI. Analyze the following {len(summary_data)} closed trades and generate actionable insights.

Trades:
{json.dumps(summary_data, indent=2)}

Return a JSON array of insights. Each insight MUST have these fields:
- type: one of PATTERN, TRAP, EXECUTION, PARAM_SUGGESTION
- title: concise title (max 80 chars)
- summary: explain the pattern or recommendation (2-3 sentences)
- confidence: float 0.0-1.0
- win_rate_impact: estimated delta in win rate (float, can be negative)
- regime: regime name if regime-specific, null if universal
- symbol: symbol if stock-specific, null if universal
- evidence: {{"sample_size": N, "avg_pnl": X, "pattern": "..."}}
- actionable_rule: {{"action": "...", "condition": "...", "params": {{}}}}

Focus on high-confidence (>0.65) reproducible patterns. Generate 3-7 insights.
Return ONLY a valid JSON array, no markdown.
"""

            response = await client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            raw = (response.choices[0].message.content or "").strip()
            # 清理 markdown
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            # 1) 直接解析
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass

            # 2) 从混合文本中提取 JSON 数组
            m = re.search(r"\[.*\]", raw, flags=re.S)
            if m:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, list):
                    return parsed

            return []

        except Exception as e:
            logger.error(f"[WeeklyInsight] deepseek call failed: {e}", exc_info=True)
            return []

    def _rule_based_insights(self, trade_data: list[dict]) -> list[dict]:
        """当 AI 调用失败时，基于统计结果生成最小可用洞察。"""
        if not trade_data:
            return []

        n = len(trade_data)
        wins = [t for t in trade_data if str(t.get("category", "")).upper() == "WIN"]
        losses = [t for t in trade_data if str(t.get("category", "")).upper() == "LOSS"]
        win_rate = len(wins) / n if n else 0.0

        def avg(items: list[dict], key: str) -> float:
            vals = [float(i.get(key) or 0.0) for i in items]
            return sum(vals) / len(vals) if vals else 0.0

        avg_win = avg(wins, "pnl_pct")
        avg_loss = avg(losses, "pnl_pct")
        avg_exec_win = avg(wins, "execution_score")
        avg_exec_loss = avg(losses, "execution_score")

        insights: list[dict] = []

        insights.append(
            {
                "type": "PATTERN" if win_rate >= 0.5 else "TRAP",
                "title": f"近30天样本胜率 {win_rate * 100:.1f}% 的交易行为特征",
                "summary": (
                    f"样本数 {n}，平均盈利单 {avg_win * 100:.2f}% ，平均亏损单 {avg_loss * 100:.2f}% 。"
                    "建议围绕高质量入场条件做筛选，并减少低把握度信号频次。"
                ),
                "confidence": 0.66,
                "win_rate_impact": 0.02 if win_rate < 0.5 else 0.01,
                "regime": None,
                "symbol": None,
                "evidence": {"sample_size": n, "win_rate": round(win_rate, 4)},
                "actionable_rule": {
                    "action": "FILTER_SIGNALS",
                    "condition": "仅执行置信度Top分位信号",
                    "params": {"min_confidence_quantile": 0.7},
                },
            }
        )

        if (avg_exec_win - avg_exec_loss) > 0.08:
            insights.append(
                {
                    "type": "EXECUTION",
                    "title": "执行质量与盈亏相关性显著",
                    "summary": "高执行质量样本显著优于低执行质量样本，建议优先在流动性充足时段执行。",
                    "confidence": 0.68,
                    "win_rate_impact": 0.015,
                    "regime": None,
                    "symbol": None,
                    "evidence": {
                        "sample_size": n,
                        "avg_exec_win": round(avg_exec_win, 4),
                        "avg_exec_loss": round(avg_exec_loss, 4),
                    },
                    "actionable_rule": {
                        "action": "EXECUTION_OPTIMIZE",
                        "condition": "流动性不足或冲击成本偏高时降速",
                        "params": {"prefer_algo": "TWAP", "slippage_cap_bps": 25},
                    },
                }
            )

        return insights[:4]

    @staticmethod
    def _insight_event_payload(insight: AIInsight) -> dict:
        """避免访问可能触发懒加载的字段（如 server_default 时间列）。"""
        return {
            "id": insight.id,
            "insight_type": insight.insight_type,
            "regime": insight.regime,
            "symbol": insight.symbol,
            "title": insight.title,
            "summary": insight.summary,
            "confidence": insight.confidence,
            "active": insight.active,
            "created_by_job": insight.created_by_job,
        }


class ABTestEngine:
    """
    自动参数 A/B 实验引擎。

    使用 scipy.stats.ttest_ind 对配对数据进行 Welch's t-test，
    p < 0.05 且实验组优于对照组时自动标记通过。
    """

    async def create_experiment(
        self,
        db: AsyncSession,
        insight_id: Optional[int],
        experiment_name: str,
        param_key: str,
        control_value: dict,
        treatment_value: dict,
        duration_days: int = 14,
    ) -> ABExperiment:
        exp = ABExperiment(
            insight_id=insight_id,
            experiment_name=experiment_name,
            param_key=param_key,
            control_value=control_value,
            treatment_value=treatment_value,
            status=ExperimentStatus.RUNNING,
            start_date=datetime.now(tz=timezone.utc),
            duration_days=duration_days,
        )
        db.add(exp)
        await db.commit()
        await db.refresh(exp)
        logger.info(f"[ABTest] created experiment '{experiment_name}' id={exp.id}")
        return exp

    async def evaluate_experiment(
        self,
        db: AsyncSession,
        experiment_id: int,
        control_results: list[float],  # 对照组每笔 pnl_pct
        treatment_results: list[float],  # 实验组每笔 pnl_pct
    ) -> ABExperiment:
        """执行 t-test 并更新实验状态。"""
        from scipy import stats  # type: ignore

        exp = (
            (
                await db.execute(
                    select(ABExperiment).where(ABExperiment.id == experiment_id)
                )
            )
            .scalars()
            .first()
        )
        if not exp:
            raise ValueError(f"Experiment {experiment_id} not found")

        if len(control_results) < 5 or len(treatment_results) < 5:
            logger.info(f"[ABTest] exp {experiment_id}: insufficient data, skipping")
            return exp

        # explicitly cast to float to appease type checker
        # some callers may pass tuples/Any; silence type checker with ignores
        control_wr: float = float(sum(1 for r in control_results if float(r) > 0)) / len(control_results)  # type: ignore[arg-type]
        treatment_wr: float = float(sum(1 for r in treatment_results if float(r) > 0)) / len(treatment_results)  # type: ignore[arg-type]
        _, p_value = stats.ttest_ind(
            control_results, treatment_results, equal_var=False
        )
        p_value = float(p_value)  # type: ignore[arg-type]

        passed = (p_value < 0.05) and (treatment_wr > control_wr)

        await db.execute(
            update(ABExperiment)
            .where(ABExperiment.id == experiment_id)
            .values(
                control_win_rate=round(float(control_wr), 4),
                treatment_win_rate=round(float(treatment_wr), 4),
                control_trades=len(control_results),
                treatment_trades=len(treatment_results),
                p_value=round(p_value, 6),
                passed_significance=passed,
                status=ExperimentStatus.COMPLETED,
                end_date=datetime.now(tz=timezone.utc),
                auto_applied=passed,
            )
        )
        await db.commit()

        await db.refresh(exp)
        await event_bus.publish(Topics.AB_EXPERIMENT_DONE, exp.to_dict())
        logger.info(
            f"[ABTest] exp {experiment_id} done: p={p_value:.4f} "
            f"ctrl_wr={control_wr:.2%} treat_wr={treatment_wr:.2%} passed={passed}"
        )
        return exp

    async def list_experiments(
        self,
        db: AsyncSession,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[ABExperiment]:
        stmt = (
            select(ABExperiment).order_by(ABExperiment.start_date.desc()).limit(limit)
        )
        if status:
            stmt = stmt.where(ABExperiment.status == status)
        return list((await db.execute(stmt)).scalars().all())


# ── 模块级单例 ────────────────────────────────────────────────────────────────
insight_service = InsightService()
weekly_insight_generator = WeeklyInsightGenerator()
ab_test_engine = ABTestEngine()
