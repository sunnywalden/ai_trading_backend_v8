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
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import event_bus, Topics
from app.models.ai_insight import ABExperiment, AIInsight, ExperimentStatus, InsightType

logger = logging.getLogger(__name__)


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

    async def get_insight(self, db: AsyncSession, insight_id: int) -> Optional[AIInsight]:
        return (await db.execute(select(AIInsight).where(AIInsight.id == insight_id))).scalars().first()

    async def create_insight(self, db: AsyncSession, data: dict) -> AIInsight:
        insight = AIInsight(**data)
        db.add(insight)
        await db.commit()
        await db.refresh(insight)
        await event_bus.publish(Topics.INSIGHT_GENERATED, insight.to_dict())
        return insight

    async def toggle_active(self, db: AsyncSession, insight_id: int, active: bool) -> bool:
        result = await db.execute(
            update(AIInsight).where(AIInsight.id == insight_id).values(active=active)
        )
        await db.commit()
        # rowcount not defined in stub
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def record_application(self, db: AsyncSession, insight_id: int, success: bool) -> None:
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
                await event_bus.publish(Topics.INSIGHT_GENERATED, insight.to_dict())
            except Exception as e:
                logger.warning(f"[WeeklyInsight] failed to persist insight: {e}")

        await db.commit()
        logger.info(f"[WeeklyInsight] generated {len(created)} new insights")
        return created

    async def _fetch_recent_trades(self, db: AsyncSession) -> list[dict]:
        """从 trade_attribution_entries 拉取最近 30 天数据"""
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
        return [r.to_dict() for r in rows]

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
            return json.loads(raw)

        except Exception as e:
            logger.error(f"[WeeklyInsight] deepseek call failed: {e}", exc_info=True)
            return []


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
        control_results: list[float],    # 对照组每笔 pnl_pct
        treatment_results: list[float],  # 实验组每笔 pnl_pct
    ) -> ABExperiment:
        """执行 t-test 并更新实验状态。"""
        from scipy import stats  # type: ignore

        exp = (await db.execute(
            select(ABExperiment).where(ABExperiment.id == experiment_id)
        )).scalars().first()
        if not exp:
            raise ValueError(f"Experiment {experiment_id} not found")

        if len(control_results) < 5 or len(treatment_results) < 5:
            logger.info(f"[ABTest] exp {experiment_id}: insufficient data, skipping")
            return exp

        # explicitly cast to float to appease type checker
        # some callers may pass tuples/Any; silence type checker with ignores
        control_wr: float = float(sum(1 for r in control_results   if float(r) > 0)) / len(control_results)  # type: ignore[arg-type]
        treatment_wr: float = float(sum(1 for r in treatment_results if float(r) > 0)) / len(treatment_results)  # type: ignore[arg-type]
        _, p_value = stats.ttest_ind(control_results, treatment_results, equal_var=False)
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
        stmt = select(ABExperiment).order_by(ABExperiment.start_date.desc()).limit(limit)
        if status:
            stmt = stmt.where(ABExperiment.status == status)
        return list((await db.execute(stmt)).scalars().all())


# ── 模块级单例 ────────────────────────────────────────────────────────────────
insight_service            = InsightService()
weekly_insight_generator   = WeeklyInsightGenerator()
ab_test_engine             = ABTestEngine()
