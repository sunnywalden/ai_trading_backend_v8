"""
V10: 全新Dashboard聚合服务
整合所有核心模块，提供全景式监控数据
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import asyncio
import logging

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.equity_snapshot import EquitySnapshot
from app.models.trading_plan import TradingPlan
from app.models.price_alert import AlertHistory, PriceAlert
from app.models.trading_signal import TradingSignal, SignalStatus
from app.models.strategy import StrategyRun
from app.schemas.dashboard_v2 import (
    DashboardV2Response,
    DashboardQuickUpdate,
    AccountOverview,
    PnLMetrics,
    PnLAttribution,
    RiskMetrics,
    GreeksExposure,
    RiskLevel,
    TrendDirection,
    MacroRiskAlert,
    SignalSummary,
    SignalPipeline,
    PositionSummary,
    TradingPlanSummary,
    ExecutionStats,
    AIInsight,
    StrategyPerformance,
    APIHealth,
    MarketHotspot,
    TodoItem,
    PerformanceTrend,
)
from app.broker.factory import make_option_broker_client
from app.services.option_exposure_service import OptionExposureService
from app.services.account_service import AccountService


logger = logging.getLogger(__name__)


class DashboardV2Service:
    """V2 Dashboard服务 - 全景式数据聚合"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.broker = make_option_broker_client()
    
    async def get_full_dashboard(self, account_id: str) -> DashboardV2Response:
        """获取完整Dashboard数据"""
        now = datetime.utcnow()
        
        # 顺序执行以避免 SQLAlchemy 会话并行冲突
        account = await self._get_account_overview(account_id)
        pnl, top_performers, top_losers = await self._get_pnl_metrics(account_id)
        risk = await self._get_risk_metrics(account_id)
        signal_pipeline, pending_signals = await self._get_signal_pipeline(account_id)
        execution = await self._get_execution_stats(account_id)
        insights = await self._get_ai_insights(account_id)
        strategies = await self._get_strategy_performance(account_id)
        api_health = await self._get_api_health()
        hotspots = await self._get_market_hotspots()
        todos = await self._get_todos(account_id)
        trend = await self._get_performance_trend(account_id, days=30)
        
        # 计算衍生指标
        signal_notifications = len([s for s in pending_signals if s.confidence > 0.8])
        insights_unread = len([i for i in insights if i.priority == "high"])
        todos_high = len([t for t in todos if t.priority == "high"])
        system_alerts = len([a for a in api_health if a.status != "healthy"])
        
        # 获取持仓数据
        positions_summary = await self._get_positions_summary(account_id)
        positions_count = len(positions_summary)
        
        return DashboardV2Response(
            account_id=account_id,
            timestamp=now,
            account=account,
            pnl=pnl,
            top_performers=top_performers,
            top_losers=top_losers,
            risk=risk,
            macro_risks=await self._get_macro_risks(),
            signal_pipeline=signal_pipeline,
            pending_signals=pending_signals[:10],
            signal_notifications=signal_notifications,
            positions_count=positions_count,
            positions_summary=positions_summary,
            concentration_top5=await self._calc_concentration_top5(positions_summary),
            execution_stats=execution,
            active_plans=await self._get_active_plans(account_id),
            ai_insights=insights[:10],
            insights_unread=insights_unread,
            top_strategies=strategies[:5],
            api_health=api_health,
            system_alerts=system_alerts,
            market_hotspots=hotspots[:5],
            todos=todos,
            todos_high_priority=todos_high,
            performance_trend=trend,
            refresh_interval_seconds=30,
            last_refresh_at=now,
        )
    
    async def get_quick_update(self, account_id: str) -> DashboardQuickUpdate:
        """获取快速更新（仅核心指标）"""
        equity = await self._get_current_equity(account_id)
        daily_pnl, daily_return = await self._get_daily_pnl(account_id)
        risk_level = await self._assess_risk_level(account_id)
        
        # 并行获取计数
        counts = await asyncio.gather(
            self._count_pending_signals(account_id),
            self._count_todos(account_id),
            self._count_system_alerts(),
        )
        
        return DashboardQuickUpdate(
            account_id=account_id,
            timestamp=datetime.utcnow(),
            total_equity=equity,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return,
            risk_level=risk_level,
            pending_signals_count=counts[0],
            todos_count=counts[1],
            system_alerts_count=counts[2],
        )
    
    # ============ 账户相关 ============
    async def _get_account_overview(self, account_id: str) -> AccountOverview:
        """获取账户概览"""
        try:
            account_svc = AccountService(self.session, self.broker)
            acct_info = await account_svc.get_account_info(account_id)
            equity = await self.broker.get_account_equity(account_id)
            
            return AccountOverview(
                total_equity=float(equity or 0),
                cash=acct_info.get("cash", 0.0),
                market_value=acct_info.get("market_value", 0.0),
                buying_power=acct_info.get("buying_power", 0.0),
                margin_used=acct_info.get("margin_used", 0.0),
                margin_available=acct_info.get("margin_available", 0.0),
            )
        except Exception as e:
            logger.error(f"获取账户概览失败: {e}")
            return AccountOverview()
    
    async def _get_current_equity(self, account_id: str) -> float:
        """获取当前权益"""
        try:
            equity = await self.broker.get_account_equity(account_id)
            return float(equity or 0)
        except:
            return 0.0
    
    # ============ 盈亏相关 ============
    async def _get_pnl_metrics(self, account_id: str) -> tuple[PnLMetrics, List[PnLAttribution], List[PnLAttribution]]:
        """获取盈亏指标"""
        today = date.today()
        
        # 获取各个时间段的收益率
        daily_pnl, daily_return = await self._get_daily_pnl(account_id)
        weekly_pnl, weekly_return = await self._calc_period_pnl_and_return(account_id, today - timedelta(days=7), today)
        mtd_pnl, mtd_return = await self._calc_period_pnl_and_return(account_id, today.replace(day=1), today)
        ytd_pnl, ytd_return = await self._calc_period_pnl_and_return(account_id, today.replace(month=1, day=1), today)
        
        # 计算趋势
        trend = TrendDirection.UP if daily_return > 0 else (
            TrendDirection.DOWN if daily_return < 0 else TrendDirection.FLAT
        )
        
        pnl = PnLMetrics(
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return,
            weekly_pnl=weekly_pnl,
            weekly_return_pct=weekly_return,
            mtd_pnl=mtd_pnl,
            mtd_return_pct=mtd_return,
            ytd_pnl=ytd_pnl,
            ytd_return_pct=ytd_return,
            trend=trend,
        )
        
        # 获取盈亏归因
        performers, losers = await self._get_pnl_attribution(account_id)
        
        return pnl, performers, losers
    
    async def _get_daily_pnl(self, account_id: str) -> tuple[float, float]:
        """获取今日盈亏"""
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        # 优先使用实时权益对比昨日快照
        curr_eq = await self._get_current_equity(account_id)
        yesterday_snap = await self._get_snapshot(account_id, yesterday)
        
        # 如果没有昨日快照，找最近一个早于今天的快照
        if not yesterday_snap:
            stmt = select(EquitySnapshot).where(
                and_(
                    EquitySnapshot.account_id == account_id,
                    EquitySnapshot.snapshot_date < today
                )
            ).order_by(desc(EquitySnapshot.snapshot_date)).limit(1)
            result = await self.session.execute(stmt)
            yesterday_snap = result.scalar()

        if curr_eq > 0 and yesterday_snap:
            prev_eq = float(yesterday_snap.total_equity)
            if prev_eq > 0:
                pnl = curr_eq - prev_eq
                return pnl, (pnl / prev_eq * 100)
        
        return 0.0, 0.0
    
    async def _calc_period_pnl_and_return(self, account_id: str, start: date, end: date) -> tuple[float, float]:
        """计算期间盈亏金额和收益率"""
        stmt = select(EquitySnapshot).where(
            and_(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date >= start,
                EquitySnapshot.snapshot_date <= end,
            )
        ).order_by(EquitySnapshot.snapshot_date)
        result = await self.session.execute(stmt)
        snaps = list(result.scalars().all())
        
        # 获取当前权益作为补充，以防近期快照缺失
        curr_eq = await self._get_current_equity(account_id)
        
        if not snaps:
            return 0.0, 0.0
            
        first_eq = float(snaps[0].total_equity)
        
        # 如果 end 是今天且当前有实时权益，使用实时权益作为结束点
        if end >= date.today() and curr_eq > 0:
            last_eq = curr_eq
        else:
            if len(snaps) < 2:
                return 0.0, 0.0
            last_eq = float(snaps[-1].total_equity)

        if first_eq <= 0:
            return 0.0, 0.0
        
        pnl = last_eq - first_eq
        return pnl, (pnl / first_eq * 100)
    
    async def _get_snapshot(self, account_id: str, d: date) -> Optional[EquitySnapshot]:
        """获取快照"""
        stmt = select(EquitySnapshot).where(
            and_(EquitySnapshot.account_id == account_id, EquitySnapshot.snapshot_date == d)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
    
    async def _get_pnl_attribution(self, account_id: str) -> tuple[List[PnLAttribution], List[PnLAttribution]]:
        """获取盈亏归因（Top贡献者和亏损者）"""
        try:
            # 获取当前持仓的未实现盈亏作为归因参考
            stk_positions = await self.broker.list_underlying_positions(account_id)
            opt_positions = await self.broker.list_option_positions(account_id)
            
            all_attrs = []
            for p in stk_positions:
                all_attrs.append(PnLAttribution(
                    symbol=p.symbol,
                    contribution=float(p.unrealized_pnl),
                    contribution_pct=float(p.unrealized_pnl_pct),
                    position_size=float(p.market_value),
                ))
            
            for p in opt_positions:
                all_attrs.append(PnLAttribution(
                    symbol=p.contract.broker_symbol,
                    contribution=float(p.unrealized_pnl or 0),
                    contribution_pct=float(p.unrealized_pnl_pct),
                    position_size=float(p.market_value or 0),
                ))
                
            # 分离盈利和亏损
            performers = [a for a in all_attrs if a.contribution > 0]
            losers = [a for a in all_attrs if a.contribution < 0]
            
            # 排序并取Top5
            performers = sorted(performers, key=lambda x: x.contribution, reverse=True)[:5]
            losers = sorted(losers, key=lambda x: x.contribution)[:5]
            
            return performers, losers
        except Exception as e:
            logger.error(f"获取盈亏归因失败: {e}")
            return [], []
    
    # ============ 风险相关 ============
    async def _get_risk_metrics(self, account_id: str) -> RiskMetrics:
        """获取风险指标"""
        try:
            # 获取Greeks敞口
            expo_svc = OptionExposureService(self.session, self.broker)
            expo = await expo_svc.get_account_exposure(account_id)
            eq = expo.equity_usd or 1.0
            
            greeks = GreeksExposure(
                delta=expo.total_delta_notional_usd,
                delta_pct=expo.total_delta_notional_usd / eq * 100,
                gamma=expo.total_gamma_usd,
                gamma_pct=expo.total_gamma_usd / eq * 100,
                vega=expo.total_vega_usd,
                vega_pct=expo.total_vega_usd / eq * 100,
                theta=expo.total_theta_usd,
                theta_pct=expo.total_theta_usd / eq * 100,
            )
            
            # 评估风险等级
            max_pct = max(abs(greeks.delta_pct), abs(greeks.gamma_pct), 
                         abs(greeks.vega_pct), abs(greeks.theta_pct))
            if max_pct > 80:
                risk_level = RiskLevel.EXTREME
            elif max_pct > 60:
                risk_level = RiskLevel.HIGH
            elif max_pct > 40:
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.LOW
            
            # 通过 VaRCalculator 获取实时风险指标
            var_data: dict = {}
            try:
                from app.services.var_calculator import VaRCalculator
                var_data = await VaRCalculator(self.session).calculate_var_cvar(account_id, eq)
            except Exception as _ve:
                logger.error(f"VaR calculation failed: {_ve}")

            var_1d   = abs(float(var_data.get("var_95_pct", 0.0))) * 100  # 转为百分比
            var_5d   = abs(float(var_data.get("var_99_pct", 0.0))) * 100
            max_dd   = abs(float(var_data.get("max_drawdown_pct", 0.0))) * 100
            sharpe   = float(var_data.get("sharpe_ratio", 0.0))
            beta_val = float(var_data.get("beta", 0.0))
            
            # 计算集中度风险
            conc_risk = 0.0
            stk_positions = await self.broker.list_underlying_positions(account_id)
            if stk_positions:
                max_val = max(abs(p.market_value) for p in stk_positions)
                conc_risk = (max_val / eq) * 100 if eq > 0 else 0.0

            return RiskMetrics(
                risk_level=risk_level,
                var_1d=var_1d,
                var_5d=var_5d,
                max_drawdown=max_dd,
                sharpe_ratio=sharpe,
                beta=beta_val,
                concentration_risk=conc_risk,
                greeks=greeks,
            )
        except Exception as e:
            logger.error(f"获取风险指标失败: {e}")
            return RiskMetrics()
    
    async def _assess_risk_level(self, account_id: str) -> RiskLevel:
        """评估风险等级"""
        try:
            risk = await self._get_risk_metrics(account_id)
            return risk.risk_level
        except:
            return RiskLevel.LOW
    
    async def _get_macro_risks(self) -> List[MacroRiskAlert]:
        """获取宏观风险告警（通过 MacroRiskScoringService 实时生成）"""
        try:
            from app.services.macro_risk_scoring_service import MacroRiskScoringService
            alerts_raw = await MacroRiskScoringService().generate_risk_alerts()
            now = datetime.utcnow()
            return [
                MacroRiskAlert(
                    event_type=a.get("type", "UNKNOWN"),
                    severity=a.get("level", "INFO"),
                    title=a.get("type", "宏观风险").replace("_", " ").title(),
                    description=a.get("message", ""),
                    impact_score=float(a.get("score", 0.0)),
                    timestamp=now,
                )
                for a in (alerts_raw or [])
            ]
        except Exception as e:
            logger.warning(f"MacroRisk alerts failed: {e}")
            return []
    
    # ============ 信号相关 ============
    async def _get_signal_pipeline(self, account_id: str) -> tuple[SignalPipeline, List[SignalSummary]]:
        """获取信号管道统计"""
        try:
            # 统计各状态信号数量
            stmt = select(
                TradingSignal.status, func.count(TradingSignal.signal_id)
            ).where(
                TradingSignal.account_id == account_id
            ).group_by(TradingSignal.status)
            result = await self.session.execute(stmt)
            rows = result.all()
            status_counts: Dict[SignalStatus, int] = {row[0]: int(row[1]) for row in rows}
            
            generated = status_counts.get(SignalStatus.GENERATED, 0)
            validated = status_counts.get(SignalStatus.VALIDATED, 0)
            executed = status_counts.get(SignalStatus.EXECUTED, 0)
            rejected = status_counts.get(SignalStatus.REJECTED, 0)
            
            total = generated + validated + executed + rejected
            success_rate = (executed / total * 100) if total > 0 else 0.0
            
            pipeline = SignalPipeline(
                generated_count=generated,
                validated_count=validated,
                executed_count=executed,
                rejected_count=rejected,
                success_rate=success_rate,
            )
            
            # 获取待执行信号
            stmt = select(TradingSignal).where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.status == SignalStatus.VALIDATED,
                )
            ).order_by(desc(TradingSignal.confidence)).limit(10)
            result = await self.session.execute(stmt)
            signals = result.scalars().all()
            
            signal_summaries = [
                SignalSummary(
                    signal_id=str(s.signal_id),
                    symbol=str(s.symbol),
                    signal_type=str(s.signal_type.value if hasattr(s.signal_type, "value") else s.signal_type),
                    direction=str(s.direction),
                    confidence=float(s.confidence) if s.confidence is not None else 0.0,
                    expected_return=float(s.expected_return) if s.expected_return is not None else 0.0,
                    risk_score=float(s.risk_score) if s.risk_score is not None else 0.0,
                    timestamp=s.generated_at,
                )
                for s in signals
            ]
            
            return pipeline, signal_summaries
        except Exception as e:
            logger.error(f"获取信号管道失败: {e}")
            return SignalPipeline(), []
    
    async def _count_pending_signals(self, account_id: str) -> int:
        """统计待执行信号数量"""
        stmt = select(func.count(TradingSignal.signal_id)).where(
            and_(
                TradingSignal.account_id == account_id,
                TradingSignal.status == SignalStatus.VALIDATED,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
    
    # ============ 持仓相关 ============
    async def _get_positions_summary(self, account_id: str) -> List[PositionSummary]:
        """获取持仓摘要"""
        try:
            # 1. 获取股票持仓
            stk_positions = await self.broker.list_underlying_positions(account_id)
            # 2. 获取期权持仓
            opt_positions = await self.broker.list_option_positions(account_id)
            
            # 获取总权益用于计算权重
            total_equity = await self._get_current_equity(account_id) or 1.0
            
            results = []
            
            # 处理股票
            for p in stk_positions:
                quantity = float(p.quantity)
                last_price = float(p.last_price or 0)
                avg_price = float(p.avg_price or 0)
                market_value = last_price * quantity
                unrealized_pnl = (last_price - avg_price) * quantity
                unrealized_pnl_pct = (last_price / avg_price - 1) * 100 if avg_price != 0 else 0.0
                
                results.append(PositionSummary(
                    symbol=p.symbol,
                    name=p.name or p.symbol,
                    quantity=quantity,
                    avg_cost=avg_price,
                    current_price=last_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    weight=abs(market_value) / total_equity * 100,
                    risk_score=0.0,
                    technical_score=0.0,
                    fundamental_score=0.0,
                ))
            
            # 处理期权
            for p in opt_positions:
                quantity = float(p.quantity)
                last_price = float(p.last_price or 0)
                avg_price = float(p.avg_price or 0)
                # 计算期权代码 (e.g. AAPL 240621C165)
                full_symbol = p.contract.broker_symbol
                market_value = last_price * quantity * p.contract.multiplier
                unrealized_pnl = (last_price - avg_price) * quantity * p.contract.multiplier
                unrealized_pnl_pct = (last_price / avg_price - 1) * 100 if avg_price != 0 else 0.0
                
                results.append(PositionSummary(
                    symbol=full_symbol,
                    name=full_symbol,
                    quantity=quantity,
                    avg_cost=avg_price,
                    current_price=last_price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    weight=abs(market_value) / total_equity * 100,
                    risk_score=0.0,
                    technical_score=0.0,
                    fundamental_score=0.0,
                ))
            
            # 按市值排序显示前10
            return sorted(results, key=lambda x: abs(x.market_value), reverse=True)
        except Exception as e:
            logger.error(f"获取持仓摘要失败: {e}", exc_info=True)
            return []
    
    async def _calc_concentration_top5(self, positions: List[PositionSummary]) -> float:
        """计算Top5集中度"""
        if not positions:
            return 0.0
        total_mv = sum(abs(p.market_value) for p in positions)
        if total_mv == 0:
            return 0.0
        top5_mv = sum(abs(p.market_value) for p in positions[:5])
        return (top5_mv / total_mv * 100)
    
    # ============ 交易计划相关 ============
    async def _get_execution_stats(self, account_id: str) -> ExecutionStats:
        """获取执行统计"""
        today = date.today()
        
        # 活跃计划数
        stmt = select(func.count(TradingPlan.id)).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "ACTIVE",
            )
        )
        result = await self.session.execute(stmt)
        active = result.scalar() or 0
        
        # 今日执行数
        stmt = select(func.count(TradingPlan.id)).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "EXECUTED",
                func.date(TradingPlan.updated_at) == today,
            )
        )
        result = await self.session.execute(stmt)
        executed = result.scalar() or 0
        
        # 今日取消数
        stmt = select(func.count(TradingPlan.id)).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "CANCELLED",
                func.date(TradingPlan.updated_at) == today,
            )
        )
        result = await self.session.execute(stmt)
        cancelled = result.scalar() or 0

        total_closed = executed + cancelled
        exec_rate = round(executed / total_closed * 100, 1) if total_closed > 0 else 0.0

        # 平均滑点：从 TradePnlAttribution 估算（今日已平仓记录）
        avg_slippage = 0.0
        try:
            from app.models.trade_pnl_attribution import TradePnlAttribution
            slip_stmt = select(
                func.avg(
                    func.abs(
                        (TradePnlAttribution.exit_price - TradePnlAttribution.entry_price)
                        / TradePnlAttribution.entry_price
                    ) * 100
                )
            ).where(
                and_(
                    TradePnlAttribution.account_id == account_id,
                    func.date(TradePnlAttribution.trade_date) == today,
                )
            )
            slip_result = await self.session.execute(slip_stmt)
            raw = slip_result.scalar()
            avg_slippage = round(float(raw), 4) if raw is not None else 0.0
        except Exception as _se:
            logger.debug(f"Slippage calc skipped: {_se}")

        return ExecutionStats(
            active_plans=active,
            executed_today=executed,
            cancelled_today=cancelled,
            execution_rate=exec_rate,
            avg_slippage=avg_slippage,
        )
    
    async def _get_active_plans(self, account_id: str) -> List[TradingPlanSummary]:
        """获取活跃计划"""
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "ACTIVE",
            )
        ).order_by(desc(TradingPlan.created_at)).limit(10)
        result = await self.session.execute(stmt)
        plans = result.scalars().all()
        
        return [
            TradingPlanSummary(
                plan_id=str(p.id),
                symbol=str(p.symbol),
                plan_type=str(p.plan_type),
                status=str(p.plan_status),
                target_price=float(p.take_profit) if p.take_profit is not None else None,
                quantity=0.0,
                created_at=p.created_at,
                expires_at=p.valid_until,
            )
            for p in plans
        ]
    
    # ============ AI洞察相关 ============
    async def _get_ai_insights(self, account_id: str) -> List[AIInsight]:
        """获取AI洞察 (基准规则引擎版)"""
        insights = []
        now = datetime.utcnow()
        
        try:
            # 1. 检查集中度
            positions = await self._get_positions_summary(account_id)
            if positions:
                top1 = positions[0]
                if top1.weight > 40:
                    insights.append(AIInsight(
                        insight_id="risk_concentration",
                        insight_type="risk",
                        priority="high",
                        title="高仓位集中度警告",
                        content=f"单一标的 {top1.symbol} 权重达 {top1.weight:.1f}%，超出 40% 安全阈值。建议考虑减仓或对冲。",
                        action_label="查看详情",
                        action_link="/quant-loop",
                        created_at=now
                    ))
            
            # 2. 检查待执行信号
            pipeline, pending = await self._get_signal_pipeline(account_id)
            if pending:
                high_conf = [s for s in pending if s.confidence > 0.8]
                if high_conf:
                    insights.append(AIInsight(
                        insight_id="opportunity_signals",
                        insight_type="opportunity",
                        priority="medium",
                        title="高置信度交易机会",
                        content=f"发现 {len(high_conf)} 个置信度高于 80% 的交易信号（如 {high_conf[0].symbol}），建议尽快审核执行。",
                        action_label="去执行",
                        action_link="/quant-loop",
                        created_at=now
                    ))

            # 3. 总体状态
            if not insights:
                insights.append(AIInsight(
                    insight_id="status_normal",
                    insight_type="info",
                    priority="low",
                    title="组合状态良好",
                    content="当前账户风险指标均在正常范围内，暂时没有需要处理的紧急事项。行情波动平稳。",
                    action_label="查看风控",
                    action_link="/quant-loop",
                    created_at=now
                ))
            
            # 4. 权益趋势
            trend = await self._get_performance_trend(account_id, days=7)
            if len(trend) >= 2:
                ret_7d = (trend[-1].equity / trend[0].equity - 1) * 100
                if ret_7d > 5:
                    insights.append(AIInsight(
                        insight_id="perf_good",
                        insight_type="advice",
                        priority="medium",
                        title="近期业绩优异",
                        content=f"过去 7 天组合收益率达 {ret_7d:.1f}%。建议锁住部分利润，或对现有盈利持仓上移止盈位。",
                        action_label="调整计划",
                        action_link="/plans",
                        created_at=now
                    ))

        except Exception as e:
            logger.error(f"生成AI洞察失败: {e}")
            insights.append(AIInsight(
                insight_id="error",
                insight_type="info",
                priority="low",
                title="AI 洞察初始化中",
                content="正在分析您的账户数据，请稍后刷新...",
                action_label="刷新",
                action_link="/dashboard",
                created_at=now
            ))
            
        return insights
    
    # ============ 策略相关 ============
    async def _get_strategy_performance(self, account_id: str) -> List[StrategyPerformance]:
        """从 strategy_runs + strategies 聚合策略表现"""
        try:
            from app.models.strategy import StrategyRun as SR, Strategy as Strat
            from sqlalchemy import case, join
            stmt = (
                select(
                    SR.strategy_id,
                    Strat.name.label("strategy_name"),
                    Strat.last_run_status,
                    func.count(SR.id).label("total_runs"),
                    func.avg(
                        case((SR.status == "COMPLETED", 1), else_=0)
                    ).label("success_rate"),
                    func.max(SR.finished_at).label("last_run_at"),
                )
                .select_from(SR)
                .outerjoin(Strat, Strat.id == SR.strategy_id)
                .where(SR.account_id == account_id)
                .group_by(SR.strategy_id, Strat.name, Strat.last_run_status)
                .order_by(desc(func.max(SR.finished_at)))
                .limit(10)
            )
            result = await self.session.execute(stmt)
            rows = result.all()

            return [
                StrategyPerformance(
                    strategy_id=str(row.strategy_id),
                    strategy_name=str(row.strategy_name or row.strategy_id),
                    total_runs=int(row.total_runs),
                    win_rate=float(row.success_rate or 0),
                    avg_return=0.0,
                    sharpe=0.0,
                    last_run_at=row.last_run_at,
                    status=str(row.last_run_status or "UNKNOWN"),
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Strategy performance query failed: {e}")
            return []
    
    # ============ 系统健康相关 ============
    async def _get_api_health(self) -> List[APIHealth]:
        """运行时探针检测 Tiger SDK 和 yfinance 可用性"""
        results: List[APIHealth] = []

        # Tiger 探针
        tiger_status = "degraded"
        tiger_latency = 9999.0
        try:
            from app.broker.factory import get_tiger_client
            import time
            tc = get_tiger_client()
            if tc is not None:
                t0 = time.monotonic()
                # 只做一个轻量级 quote_client 心跳探测
                await asyncio.wait_for(
                    asyncio.to_thread(lambda: tc.quote_client.get_symbols()),
                    timeout=5.0,
                )
                tiger_latency = round((time.monotonic() - t0) * 1000, 1)
                tiger_status = "healthy"
            else:
                tiger_status = "down"
        except Exception:
            tiger_status = "degraded"
        results.append(APIHealth(
            provider="Tiger OpenAPI",
            status=tiger_status,
            success_rate=1.0 if tiger_status == "healthy" else 0.0,
            avg_latency_ms=tiger_latency if tiger_status == "healthy" else 0.0,
            rate_limit_remaining=999,
            rate_limit_reset_at=None,
        ))

        # yfinance 探针
        yf_status = "degraded"
        yf_latency = 9999.0
        try:
            import time, yfinance as yf
            t0 = time.monotonic()
            info = await asyncio.wait_for(
                asyncio.to_thread(lambda: yf.Ticker("SPY").fast_info.last_price),
                timeout=8.0,
            )
            yf_latency = round((time.monotonic() - t0) * 1000, 1)
            yf_status = "healthy" if info else "degraded"
        except Exception:
            yf_status = "degraded"
        results.append(APIHealth(
            provider="yfinance",
            status=yf_status,
            success_rate=1.0 if yf_status == "healthy" else 0.0,
            avg_latency_ms=yf_latency if yf_status == "healthy" else 0.0,
            rate_limit_remaining=9999,
            rate_limit_reset_at=None,
        ))

        return results
    
    async def _count_system_alerts(self) -> int:
        """统计过去 24 小时内 FAILED 的策略运行数作为系统告警数"""
        try:
            from app.models.strategy import StrategyRun as SR
            cutoff = datetime.utcnow() - timedelta(hours=24)
            stmt = select(func.count(SR.id)).where(
                and_(SR.status == "FAILED", SR.started_at >= cutoff)
            )
            result = await self.session.execute(stmt)
            return int(result.scalar() or 0)
        except Exception as e:
            logger.debug(f"count_system_alerts failed: {e}")
            return 0
    
    # ============ 市场热点相关 ============
    async def _get_market_hotspots(self) -> List[MarketHotspot]:
        """聚合近 7 天 TradingSignal 最活跃的标的作为市场热点"""
        try:
            cutoff = datetime.utcnow() - timedelta(days=7)
            stmt = (
                select(
                    TradingSignal.symbol,
                    func.count(TradingSignal.signal_id).label("cnt"),
                )
                .where(TradingSignal.created_at >= cutoff)
                .group_by(TradingSignal.symbol)
                .order_by(desc(func.count(TradingSignal.signal_id)))
                .limit(5)
            )
            result = await self.session.execute(stmt)
            rows = result.all()
            return [
                MarketHotspot(
                    category="stock",
                    topic=str(row.symbol),
                    heat_score=float(row.cnt),
                    related_symbols=[str(row.symbol)],
                    opportunities_count=int(row.cnt),
                )
                for row in rows
            ]
        except Exception as e:
            logger.debug(f"market_hotspots query failed: {e}")
            return []
    
    # ============ 待办事项相关 ============
    async def _get_todos(self, account_id: str) -> List[TodoItem]:
        """获取待办事项"""
        todos = []
        now = datetime.utcnow()
        
        # 1. 价格告警
        stmt = select(AlertHistory).where(
            AlertHistory.account_id == account_id
        ).order_by(desc(AlertHistory.trigger_time)).limit(5)
        result = await self.session.execute(stmt)
        alerts = result.scalars().all()
        
        for alert in alerts:
            trigger_price = float(alert.trigger_price) if alert.trigger_price is not None else 0.0
            todos.append(TodoItem(
                todo_type="alert",
                priority="high",
                title=f"{str(alert.symbol)} 价格告警",
                description=f"价格触及 ${trigger_price:.2f}",
                action_link=f"/alerts",
                due_at=None,
                created_at=alert.trigger_time,
            ))
        
        # 2. 到期计划
        today = date.today()
        stmt = select(TradingPlan).where(
            and_(
                TradingPlan.account_id == account_id,
                TradingPlan.plan_status == "ACTIVE",
                TradingPlan.valid_until != None,
                func.date(TradingPlan.valid_until) == today,
            )
        )
        result = await self.session.execute(stmt)
        expiring_plans = list(result.scalars().all())
        
        if expiring_plans:
            todos.append(TodoItem(
                todo_type="plan_expiring",
                priority="high",
                title=f"{len(expiring_plans)} 个计划今日到期",
                description="请及时处理即将到期的交易计划",
                action_link="/plans",
                due_at=datetime.combine(today, datetime.max.time()),
                created_at=now,
            ))
        
        # 3. 待执行信号
        signal_count = await self._count_pending_signals(account_id)
        if signal_count > 0:
            todos.append(TodoItem(
                todo_type="signal_pending",
                priority="medium",
                title=f"{signal_count} 个信号待执行",
                description="请审核并执行交易信号",
                action_link="/quant-loop",
                due_at=None,
                created_at=now,
            ))
        
        return todos
    
    async def _count_todos(self, account_id: str) -> int:
        """统计待办数量"""
        todos = await self._get_todos(account_id)
        return len(todos)
    
    # ============ 性能趋势相关 ============
    async def _get_performance_trend(self, account_id: str, days: int = 30) -> List[PerformanceTrend]:
        """获取性能趋势"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        stmt = select(EquitySnapshot).where(
            and_(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date >= start_date,
                EquitySnapshot.snapshot_date <= end_date,
            )
        ).order_by(EquitySnapshot.snapshot_date)
        result = await self.session.execute(stmt)
        snapshots = list(result.scalars().all())
        
        if not snapshots:
            return []
        
        first_equity = float(snapshots[0].total_equity)
        
        trend = []
        for i, snap in enumerate(snapshots):
            equity = float(snap.total_equity)
            if i > 0:
                prev_equity = float(snapshots[i-1].total_equity)
                pnl = equity - prev_equity
                return_pct = (pnl / prev_equity * 100) if prev_equity > 0 else 0.0
            else:
                pnl = 0.0
                return_pct = 0.0
            
            trend.append(PerformanceTrend(
                date=snap.snapshot_date.isoformat(),
                equity=equity,
                pnl=pnl,
                return_pct=return_pct,
            ))
        
        return trend
    
    # ============ 错误处理 ============
    def _get_fallback(self, index: int) -> Any:
        """获取错误回退值"""
        fallbacks = [
            AccountOverview(),
            (PnLMetrics(), [], []),
            RiskMetrics(),
            (SignalPipeline(), []),
            ExecutionStats(),
            [],
            [],
            [],
            [],
            [],
            [],
        ]
        return fallbacks[index] if index < len(fallbacks) else None
