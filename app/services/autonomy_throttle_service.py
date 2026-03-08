"""autonomy_throttle_service.py — V10.5.1 M4

自主度节流服务（Adaptive Autonomy Throttle）。

综合模型退化报告与数据陈旧度矩阵，计算推荐的自主度级别：
  - FULL      → 一切正常，全自主执行
  - SEMI      → 存在 WARNING 级别风险，人工确认后执行
  - ADVISORY  → 存在 CRITICAL 级别风险，仅给出建议不执行
  - FREEZE    → 数据严重陈旧或高风险，仅允许减仓/平仓，禁止新开仓

节流决策树：
  1. 若数据陈旧矩阵 CRITICAL 且推荐 FREEZE_NEW_OPEN → FREEZE
  2. 若模型退化有任意 CRITICAL 指标              → ADVISORY
  3. 若数据陈旧有任意 CRITICAL 来源              → ADVISORY
  4. 若模型退化 WARNING >= 2                     → SEMI
  5. 若数据陈旧 WARNING >= 2                     → SEMI
  6. 若模型退化 WARNING == 1 或数据陈旧 WARNING == 1 → SEMI
  7. 否则                                        → FULL
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_freshness_guard_service import \
    data_freshness_guard_service
from app.services.model_degradation_monitor_service import \
    model_degradation_monitor_service

_FULL = "FULL"
_SEMI = "SEMI"
_ADVISORY = "ADVISORY"
_FREEZE = "FREEZE"


class AutonomyThrottleService:
    """V10.5.1 M4 — 自主度节流服务。

    调用入参：account_id（当前用户/账户ID）
    返回：完整节流状态报告，包括推荐级别、原因、各维度分析。
    """

    async def get_throttle_status(
        self,
        db: AsyncSession,
        account_id: str,
        current_autonomy_level: str = _FULL,
    ) -> dict[str, Any]:
        """计算并返回自主度节流推荐状态。

        Args:
            db: 异步数据库会话
            account_id: 账户ID（用于 candidate key 推导）
            current_autonomy_level: 系统当前实际自主度级别

        Returns:
            包含推荐级别、原因列表、两项子报告的字典。
        """
        now = datetime.utcnow()

        # ── 子报告（并行获取）───────────────────────────────────────────────
        degradation = await model_degradation_monitor_service.get_degradation_report(
            db, account_id
        )
        freshness = await data_freshness_guard_service.get_freshness_matrix(
            db, account_id
        )

        reasons: list[str] = []
        recommended_level = _FULL

        # ── 决策树 ────────────────────────────────────────────────────────
        if freshness["freeze_new_open"]:
            recommended_level = _FREEZE
            reasons.append(
                f"数据陈旧：{', '.join(freshness['critical_sources'])} 超过 CRITICAL 阈值，触发新开仓冻结"
            )

        elif degradation["critical_count"] > 0:
            recommended_level = _ADVISORY
            critical_metrics = [
                m["metric_type"]
                for m in degradation["metrics"]
                if m["severity"] == "CRITICAL"
            ]
            reasons.append(
                f"模型退化 CRITICAL：{', '.join(critical_metrics)}"
            )

        elif freshness["critical_count"] > 0:
            recommended_level = _ADVISORY
            reasons.append(
                f"数据陈旧 CRITICAL：{', '.join(freshness['critical_sources'])}"
            )

        else:
            warn_from_degradation = degradation["warning_count"]
            warn_from_freshness = freshness["warning_count"]
            total_warnings = warn_from_degradation + warn_from_freshness

            if total_warnings > 0:
                recommended_level = _SEMI
                if warn_from_degradation > 0:
                    warn_metrics = [
                        m["metric_type"]
                        for m in degradation["metrics"]
                        if m["severity"] == "WARNING"
                    ]
                    reasons.append(f"模型退化 WARNING：{', '.join(warn_metrics)}")
                if warn_from_freshness > 0:
                    warn_sources = [
                        m["source"]
                        for m in freshness["matrix"]
                        if m["status"] == "WARNING"
                    ]
                    reasons.append(f"数据陈旧 WARNING：{', '.join(warn_sources)}")

        if not reasons:
            reasons.append("所有指标均在正常范围内")

        # ── 降级说明（仅供参考，实际变更须通过 autonomy router 执行）──────
        downgrade_needed = _level_rank(recommended_level) < _level_rank(
            current_autonomy_level
        )
        upgrade_possible = _level_rank(recommended_level) > _level_rank(
            current_autonomy_level
        )

        return {
            "as_of": now.isoformat(),
            "current_level": current_autonomy_level,
            "recommended_level": recommended_level,
            "downgrade_needed": downgrade_needed,
            "upgrade_possible": upgrade_possible,
            "reasons": reasons,
            "degradation_summary": {
                "overall_severity": degradation["overall_severity"],
                "critical_count": degradation["critical_count"],
                "warning_count": degradation["warning_count"],
                "metrics": degradation["metrics"],
            },
            "freshness_summary": {
                "overall_status": freshness["overall_status"],
                "critical_count": freshness["critical_count"],
                "warning_count": freshness["warning_count"],
                "freeze_new_open": freshness["freeze_new_open"],
                "matrix": freshness["matrix"],
            },
        }


def _level_rank(level: str) -> int:
    return {_FULL: 4, _SEMI: 3, _ADVISORY: 2, _FREEZE: 1}.get(level.upper(), 3)


autonomy_throttle_service = AutonomyThrottleService()
