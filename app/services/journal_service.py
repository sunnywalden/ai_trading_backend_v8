"""V9: 交易日志/复盘服务"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Any

from sqlalchemy import select, func, and_, desc, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.trade_journal import TradeJournal


class JournalService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    async def create_journal(self, account_id: str, payload: dict) -> TradeJournal:
        """创建交易日志"""
        journal = TradeJournal(account_id=account_id, **payload)
        self.session.add(journal)
        await self.session.commit()
        await self.session.refresh(journal)
        return journal

    async def update_journal(self, journal_id: int, account_id: str, payload: dict) -> Optional[TradeJournal]:
        """更新交易日志"""
        journal = await self._get_by_id(journal_id, account_id)
        if not journal:
            return None
        for key, value in payload.items():
            if value is not None and hasattr(journal, key):
                setattr(journal, key, value)
        await self.session.commit()
        await self.session.refresh(journal)
        return journal

    async def list_journals(
        self, account_id: str, page: int = 1, size: int = 20,
        symbol: Optional[str] = None, status: Optional[str] = None
    ) -> tuple[list[TradeJournal], int]:
        """查询交易日志列表"""
        stmt = select(TradeJournal).where(TradeJournal.account_id == account_id)
        count_stmt = select(func.count(TradeJournal.id)).where(TradeJournal.account_id == account_id)

        if symbol:
            stmt = stmt.where(TradeJournal.symbol == symbol)
            count_stmt = count_stmt.where(TradeJournal.symbol == symbol)
        if status:
            stmt = stmt.where(TradeJournal.journal_status == status)
            count_stmt = count_stmt.where(TradeJournal.journal_status == status)
        else:
            # 默认列表去噪：若同 plan_id 已有 COMPLETED，则隐藏该 plan_id 下的 FAILED 重复项
            completed_plan_ids_subq = (
                select(TradeJournal.plan_id)
                .where(
                    and_(
                        TradeJournal.account_id == account_id,
                        TradeJournal.plan_id.is_not(None),
                        TradeJournal.journal_status == "COMPLETED",
                    )
                )
            )
            noise_filter = or_(
                TradeJournal.journal_status != "FAILED",
                TradeJournal.plan_id.is_(None),
                TradeJournal.plan_id.notin_(completed_plan_ids_subq),
            )
            stmt = stmt.where(noise_filter)
            count_stmt = count_stmt.where(noise_filter)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        # 默认排序策略：优先展示 COMPLETED，随后按时间倒序（同秒再按 id 倒序）
        completed_first = case((TradeJournal.journal_status == "COMPLETED", 1), else_=0)
        stmt = stmt.order_by(desc(completed_first), desc(TradeJournal.created_at), desc(TradeJournal.id)).offset((page - 1) * size).limit(size)
        result = await self.session.execute(stmt)
        journals = list(result.scalars().all())
        return journals, total

    async def create_from_execution(
        self, account_id: str, symbol: str, direction: str, price: float, quantity: float, signal_id: Optional[str] = None
    ) -> TradeJournal:
        """从成交事件自动创建交易日志"""
        # 映射方向名称 (LONG->BUY, SHORT->SELL) 以保持一致性
        dir_map = {"LONG": "BUY", "SHORT": "SELL"}
        journal_direction = dir_map.get(direction.upper(), direction.upper())
        
        journal = TradeJournal(
            account_id=account_id,
            symbol=symbol,
            direction=journal_direction,
            entry_date=date.today(),
            entry_price=price,
            quantity=quantity,
            journal_status="DRAFT",
            signal_id=signal_id,
            lesson_learned=f"系统自动执行 {'看多' if direction.upper() == 'LONG' else '看空'} 信号 (SignalID: {signal_id})" if signal_id else "系统自动执行"
        )
        self.session.add(journal)
        await self.session.commit()
        await self.session.refresh(journal)
        return journal

    async def update_journal_by_signal(
        self, signal_id: str, updates: dict
    ) -> bool:
        """根据信号 ID 更新交易日志"""
        stmt = select(TradeJournal).where(TradeJournal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        journal = result.scalars().first()
        
        if not journal:
            return False
            
        for key, value in updates.items():
            if hasattr(journal, key):
                setattr(journal, key, value)
                
        await self.session.commit()
        return True

    async def ai_review(self, journal_id: int, account_id: str) -> Optional[str]:
        """AI 自动复盘"""
        journal = await self._get_by_id(journal_id, account_id)
        if not journal:
            return None

        # 构建 AI 复盘 prompt
        review_text = await self._generate_ai_review(journal)
        journal.ai_review = review_text  # type: ignore[assignment]
        journal.journal_status = "REVIEWED"  # type: ignore[assignment]
        await self.session.commit()
        return review_text

    async def weekly_report(self, account_id: str, week_date: date) -> dict:
        """生成 AI 周报"""
        week_start = week_date - timedelta(days=week_date.weekday())
        week_end = week_start + timedelta(days=6)

        stmt = select(TradeJournal).where(
            and_(
                TradeJournal.account_id == account_id,
                TradeJournal.entry_date >= week_start,
                TradeJournal.entry_date <= week_end,
            )
        ).order_by(TradeJournal.entry_date)
        result = await self.session.execute(stmt)
        journals = list(result.scalars().all())

        total_trades = len(journals)
        total_pnl = sum(self._as_float(getattr(j, "realized_pnl", None), 0.0) for j in journals)
        wins = sum(1 for j in journals if self._as_float(getattr(j, "realized_pnl", None), 0.0) > 0)
        win_rate = wins / max(total_trades, 1)

        report = await self._generate_weekly_report(journals, total_trades, total_pnl, win_rate)

        return {
            "week_start": week_start,
            "week_end": week_end,
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "report": report,
        }

    async def _generate_ai_review(self, journal: TradeJournal) -> str:
        """调用 AI 生成单笔交易复盘（支持 OpenAI + DeepSeek 降级）"""
        try:
            from app.services.ai_client_manager import call_ai_with_fallback

            prompt = f"""作为一位华尔街资深交易教练，请对以下交易进行复盘分析：

标的：{journal.symbol}
方向：{journal.direction}
入场日期：{journal.entry_date}  出场日期：{journal.exit_date}
入场价：{journal.entry_price}  出场价：{journal.exit_price}
数量：{journal.quantity}
已实现盈亏：${self._as_float(getattr(journal, "realized_pnl", None), 0.0):.2f}
交易者自评执行质量：{journal.execution_quality}/5
交易者情绪：{journal.emotion_state}
交易者标注的错误：{journal.mistake_tags}
交易者反思：{journal.lesson_learned}

请从以下维度给出复盘：
1. 执行质量评价（入场/出场时机、仓位管理）
2. 情绪与纪律分析
3. 改进建议（具体可操作的）
4. 本笔交易评分（0-100）

请用中文回答，控制在 300 字以内。"""

            messages = [{"role": "user", "content": prompt}]
            
            # 使用多提供商降级调用（OpenAI → DeepSeek）
            content, provider = await call_ai_with_fallback(
                messages=messages,
                max_tokens=500,
                temperature=0.7,
            )
            
            if content:
                return content.strip()
            else:
                # 所有AI提供商失败，降级到规则
                return self._rule_based_review(journal)
        except Exception as e:
            # 降级为规则复盘
            return self._rule_based_review(journal)

    def _rule_based_review(self, journal: TradeJournal) -> str:
        """规则降级复盘"""
        pnl = self._as_float(getattr(journal, "realized_pnl", None), 0.0)
        emotion = str(getattr(journal, "emotion_state", None) or "unknown")
        mistakes_raw = getattr(journal, "mistake_tags", None)
        mistakes = mistakes_raw if isinstance(mistakes_raw, list) else []

        lines = []
        if pnl > 0:
            lines.append(f"✅ 本笔交易盈利 ${pnl:.2f}。")
        else:
            lines.append(f"❌ 本笔交易亏损 ${abs(pnl):.2f}。")

        if emotion in ("revenge", "fomo", "greedy"):
            lines.append(f"⚠️ 交易情绪: {emotion}，建议下次冷静后再操作。")

        if "chase_high" in mistakes:
            lines.append("📌 追高行为：建议等待回调再入场。")
        if "sell_fly" in mistakes:
            lines.append("📌 卖飞行为：建议分批止盈，保留底仓。")
        if "no_plan" in mistakes:
            lines.append("📌 无计划入场：建议每笔交易前制定明确的交易计划。")

        quality_raw = getattr(journal, "execution_quality", None)
        quality = int(quality_raw) if quality_raw is not None else 3
        if quality <= 2:
            lines.append("🔧 执行质量较低，建议严格按计划执行。")

        return "\n".join(lines) if lines else "暂无复盘建议。"

    async def _generate_weekly_report(self, journals: list, total_trades: int, total_pnl: float, win_rate: float) -> str:
        """生成 AI 周报（支持 OpenAI + DeepSeek 降级）"""
        try:
            from app.services.ai_client_manager import call_ai_with_fallback

            trades_summary = "\n".join([
                f"- {j.symbol} {j.direction} PnL=${self._as_float(getattr(j, 'realized_pnl', None), 0.0):.2f} 情绪:{j.emotion_state}"
                for j in journals
            ])

            prompt = f"""作为交易教练，请根据以下本周交易数据生成周度复盘报告：

本周交易数：{total_trades}
总盈亏：${total_pnl:.2f}
胜率：{win_rate:.1%}

交易明细：
{trades_summary}

请从以下方面总结：
1. 本周整体表现
2. 做得好的地方
3. 需要改进的地方
4. 下周重点关注事项
5. 情绪与纪律评分

用中文回答，500 字以内。"""

            messages = [{"role": "user", "content": prompt}]
            
            # 使用多提供商降级调用（OpenAI → DeepSeek）
            content, provider = await call_ai_with_fallback(
                messages=messages,
                max_tokens=800,
                temperature=0.7,
            )
            
            if content:
                return content.strip()
            else:
                return f"本周共 {total_trades} 笔交易，总盈亏 ${total_pnl:.2f}，胜率 {win_rate:.1%}。"
        except Exception:
            return f"本周共 {total_trades} 笔交易，总盈亏 ${total_pnl:.2f}，胜率 {win_rate:.1%}。"

    async def _get_by_id(self, journal_id: int, account_id: str) -> Optional[TradeJournal]:
        stmt = select(TradeJournal).where(
            and_(TradeJournal.id == journal_id, TradeJournal.account_id == account_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
