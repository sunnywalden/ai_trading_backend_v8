"""V10.2-M5: 逐笔归因引擎 TradeAttributionEngine

三层归因体系：
  Layer-1 Alpha 来源：哪个维度的信号贡献了收益？
  Layer-2 执行质量：进出场时机 + 滑点分析
  Layer-3 仓位管理：加减仓决策的价值增减估算

结果写入 TradeAttributionEntry，定期由 WeeklyInsightJob 消费生成洞察。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade_attribution import AttributionCategory, TradeAttributionEntry

logger = logging.getLogger(__name__)


# ── 输入数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """一笔完整交易记录（从 order/position 数据构造）"""
    position_id:    int
    symbol:         str
    strategy_id:    Optional[str]

    # 价格与规模
    entry_price:    float
    exit_price:     float
    quantity:       float
    benchmark_entry: Optional[float] = None   # 基准进场价（如 VWAP）
    benchmark_exit:  Optional[float] = None   # 基准出场价

    # 生命周期
    entry_time:     Optional[datetime] = None
    exit_time:      Optional[datetime] = None
    scale_in_count:  int = 0
    scale_out_reason: Optional[str] = None
    trailing_stop_used: bool = False

    # 信号快照（在进场时点）
    alpha_detail:   dict = field(default_factory=dict)   # {'technical': 0.78, 'fundamental': 0.62, ...}
    regime_at_entry: Optional[str] = None
    regime_at_exit:  Optional[str] = None


@dataclass
class AttributionResult:
    """单笔交易的归因结果"""
    position_id:    int
    symbol:         str
    pnl_absolute:   float
    pnl_pct:        float
    hold_days:      int
    category:       str          # WIN / LOSS / BREAKEVEN

    # Layer-1
    alpha_source:            str
    alpha_contribution_pct:  float
    alpha_detail:            dict

    # Layer-2
    execution_score: float
    slippage_pct:    float
    timing_score:    float
    execution_detail: dict

    # Layer-3
    position_mgmt_score: float
    scale_in_count:      int
    scale_out_reason:    Optional[str]
    trailing_stop_used:  bool
    position_detail:     dict

    regime_at_entry: Optional[str]
    regime_at_exit:  Optional[str]


class TradeAttributionEngine:
    """
    逐笔交易三层归因引擎。

    典型调用::

        engine = TradeAttributionEngine()
        result = engine.analyze(trade_record)
        entry  = await engine.persist(db, result)
    """

    def analyze(self, trade: TradeRecord) -> AttributionResult:
        """对一笔交易执行三层归因分析，返回 AttributionResult。"""
        pnl_pct      = (trade.exit_price - trade.entry_price) / trade.entry_price
        pnl_absolute = pnl_pct * trade.quantity * trade.entry_price

        # ── 分类 ──────────────────────────────────────────────────────────────
        if pnl_pct > 0.005:
            category = AttributionCategory.WIN
        elif pnl_pct < -0.005:
            category = AttributionCategory.LOSS
        else:
            category = AttributionCategory.BREAKEVEN

        hold_days = 0
        if trade.entry_time and trade.exit_time:
            hold_days = max(0, (trade.exit_time - trade.entry_time).days)

        # ── Layer-1: Alpha 来源 ───────────────────────────────────────────────
        alpha_source, alpha_contribution_pct = self._compute_alpha_source(trade.alpha_detail, pnl_pct)

        # ── Layer-2: 执行质量 ─────────────────────────────────────────────────
        exec_score, slippage_pct, timing_score, exec_detail = self._compute_execution(trade, pnl_pct)

        # ── Layer-3: 仓位管理 ─────────────────────────────────────────────────
        pos_score, pos_detail = self._compute_position_mgmt(trade, pnl_pct)

        return AttributionResult(
            position_id=trade.position_id,
            symbol=trade.symbol,
            pnl_absolute=round(pnl_absolute, 4),
            pnl_pct=round(pnl_pct, 6),
            hold_days=hold_days,
            category=category.value,
            alpha_source=alpha_source,
            alpha_contribution_pct=round(alpha_contribution_pct, 4),
            alpha_detail=trade.alpha_detail,
            execution_score=round(exec_score, 4),
            slippage_pct=round(slippage_pct, 6),
            timing_score=round(timing_score, 4),
            execution_detail=exec_detail,
            position_mgmt_score=round(pos_score, 4),
            scale_in_count=trade.scale_in_count,
            scale_out_reason=trade.scale_out_reason,
            trailing_stop_used=trade.trailing_stop_used,
            position_detail=pos_detail,
            regime_at_entry=trade.regime_at_entry,
            regime_at_exit=trade.regime_at_exit,
        )

    async def persist(self, db: AsyncSession, result: AttributionResult) -> TradeAttributionEntry:
        """将归因结果持久化到数据库。"""
        entry = TradeAttributionEntry(
            position_id=result.position_id,
            symbol=result.symbol,
            entry_price=0,           # 原始 entry/exit 由调用方补充
            exit_price=0,
            quantity=0,
            pnl_absolute=result.pnl_absolute,
            pnl_pct=result.pnl_pct,
            hold_days=result.hold_days,
            category=result.category,
            alpha_source=result.alpha_source,
            alpha_contribution_pct=result.alpha_contribution_pct,
            alpha_detail=result.alpha_detail,
            execution_score=result.execution_score,
            slippage_pct=result.slippage_pct,
            timing_score=result.timing_score,
            execution_detail=result.execution_detail,
            position_mgmt_score=result.position_mgmt_score,
            scale_in_count=result.scale_in_count,
            scale_out_reason=result.scale_out_reason,
            trailing_stop_used=result.trailing_stop_used,
            position_detail=result.position_detail,
            regime_at_entry=result.regime_at_entry,
            regime_at_exit=result.regime_at_exit,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        logger.info(f"[Attribution] persisted entry id={entry.id} symbol={entry.symbol} pnl={entry.pnl_pct:.2%}")
        return entry

    # ── 内部：Alpha 来源分析 ──────────────────────────────────────────────────

    def _compute_alpha_source(
        self,
        alpha_detail: dict,
        pnl_pct: float,
    ) -> tuple[str, float]:
        """找出贡献最大的信号维度，估算其对最终 PnL 的贡献比例。"""
        if not alpha_detail:
            return "UNKNOWN", 0.0
        dominant = max(alpha_detail, key=lambda k: alpha_detail[k])
        dominant_score = alpha_detail[dominant]
        total_score    = sum(alpha_detail.values()) or 1.0
        contribution   = (dominant_score / total_score) * pnl_pct
        return dominant.upper(), contribution

    # ── 内部：执行质量分析 ────────────────────────────────────────────────────

    def _compute_execution(
        self,
        trade: TradeRecord,
        pnl_pct: float,
    ) -> tuple[float, float, float, dict]:
        """
        评估执行质量：
        - slippage：实际进场价 vs 基准价偏差
        - timing   ：是否在趋势早期进入
        - 综合分   ：0-1
        """
        # 滑点
        if trade.benchmark_entry and trade.entry_price:
            slippage_pct = (trade.entry_price - trade.benchmark_entry) / trade.benchmark_entry
        else:
            slippage_pct = 0.0

        # 时机评分：基础 0.5，若正向 PnL 且滑点小于 0.5% → 加分
        timing_score = 0.5
        if pnl_pct > 0 and abs(slippage_pct) < 0.005:
            timing_score = 0.80
        elif pnl_pct < 0 and slippage_pct > 0.005:
            timing_score = 0.25

        # 综合执行分
        exec_score = (1 - min(abs(slippage_pct) * 10, 0.5)) * 0.4 + timing_score * 0.6

        detail = {
            "slippage_pct":        round(slippage_pct, 6),
            "timing_score":        round(timing_score, 4),
            "benchmark_delta_pct": round(slippage_pct, 6),
        }
        return exec_score, slippage_pct, timing_score, detail

    # ── 内部：仓位管理分析 ────────────────────────────────────────────────────

    def _compute_position_mgmt(
        self,
        trade: TradeRecord,
        pnl_pct: float,
    ) -> tuple[float, dict]:
        """
        评估仓位管理质量：
        - 适度加仓（不超过 2 次加仓且 PnL > 0）加分
        - 使用追踪止损且 PnL < 0 减损可控时加分
        """
        score = 0.5
        notes = []

        if trade.scale_in_count > 0:
            if pnl_pct > 0:
                bonus = min(trade.scale_in_count * 0.1, 0.25)
                score += bonus
                notes.append(f"scale_in x{trade.scale_in_count} contributed +{bonus:.2f}")
            else:
                penalty = min(trade.scale_in_count * 0.08, 0.20)
                score -= penalty
                notes.append(f"scale_in x{trade.scale_in_count} into loss −{penalty:.2f}")

        if trade.trailing_stop_used and pnl_pct < 0:
            # 追踪止损限制了亏损
            if pnl_pct > -0.05:
                score += 0.15
                notes.append("trailing stop limited loss")
        elif trade.trailing_stop_used and pnl_pct > 0:
            score += 0.10
            notes.append("trailing stop protected partial gain")

        score = max(0.0, min(1.0, score))
        return score, {"score": round(score, 4), "notes": notes, "scale_in_count": trade.scale_in_count}

    async def get_summary(
        self,
        db: AsyncSession,
        days: int = 30,
    ) -> dict:
        """返回最近 days 天的归因汇总统计。"""
        from datetime import timedelta

        from sqlalchemy import func, select

        from app.models.trade_attribution import TradeAttributionEntry

        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        stmt = (
            select(
                TradeAttributionEntry.category,
                func.count(TradeAttributionEntry.id).label("count"),
                func.avg(TradeAttributionEntry.pnl_pct).label("avg_pnl"),
                func.avg(TradeAttributionEntry.execution_score).label("avg_exec"),
                func.avg(TradeAttributionEntry.position_mgmt_score).label("avg_pos"),
            )
            .where(TradeAttributionEntry.created_at >= since)
            .group_by(TradeAttributionEntry.category)
        )
        rows = (await db.execute(stmt)).all()
        return {
            "period_days": days,
            "breakdown": [
                {
                    "category":       r.category,
                    "count":          r.count,
                    "avg_pnl_pct":    round(r.avg_pnl or 0, 4),
                    "avg_exec_score": round(r.avg_exec or 0, 4),
                    "avg_pos_score":  round(r.avg_pos or 0, 4),
                }
                for r in rows
            ],
        }


# ── 模块级单例 ────────────────────────────────────────────────────────────────
trade_attribution_engine = TradeAttributionEngine()
