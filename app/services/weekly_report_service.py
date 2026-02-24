"""V10: WeeklyReportService — AI 周报（每周一生成上周复盘）"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)


class WeeklyReportService:
    """使用复杂推理模型生成 AI 交易周报"""

    async def generate(self, account_id: str) -> dict:
        """生成上周交易复盘报告"""
        end = date.today()
        start = end - timedelta(days=7)

        # 收集上周数据（简化：从数据库聚合）
        weekly_data = await self._collect_weekly_data(account_id, start, end)

        # 调用 AI 复杂模型生成报告
        report_text = await self._generate_report(weekly_data)

        return {
            "account_id": account_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "summary": weekly_data,
            "report": report_text,
            "generated_at": end.isoformat(),
        }

    async def _collect_weekly_data(self, account_id: str, start: date, end: date) -> dict:
        """从数据库收集上周交易数据（简化实现）"""
        return {
            "period": f"{start} ~ {end}",
            "total_trades": 0,
            "win_trades": 0,
            "lose_trades": 0,
            "total_pnl": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "strategies_ran": [],
            "ai_decisions": 0,
            "risk_gate_rejections": 0,
        }

    async def _generate_report(self, data: dict) -> str:
        """调用 AI 复杂推理模型生成周报"""
        from openai import AsyncOpenAI

        model = settings.AI_COMPLEX_MODEL

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

        prompt = f"""你是专业量化交易分析师，请基于以下过去一周的交易数据，生成详细的中文交易周报。

过去一周数据：
{json.dumps(data, ensure_ascii=False, indent=2)}

请生成包含以下模块的周报：

## 📊 一周绩效概览
[权益变化、收益率、Sharpe、最大回撤]

## ✅ 表现最佳的策略
[列出表现最好的 3 个策略及原因]

## ❌ 改进建议
[基于数据分析给出 3-5 条可操作建议]

## 🎯 下周重点关注
[基于宏观环境和当前持仓给出下周计划]

## 🔒 风控回顾
[风险门拦截次数、触发原因分析]

请用专业但易懂的语言，提供具体数据支撑。"""

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            return resp.choices[0].message.content or "报告生成失败"
        except Exception as e:
            logger.error(f"Weekly report AI generation failed: {e}")
            return f"AI 周报生成失败：{e}"


# 全局单例
weekly_report_service = WeeklyReportService()
