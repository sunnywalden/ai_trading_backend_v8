"""
V10: 全新Dashboard聚合服务
整合所有核心模块，提供全景式监控数据
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
import asyncio

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
            print(f"获取账户概览失败: {e}")
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
        weekly_return = await self._calc_period_return(account_id, today - timedelta(days=7), today)
        mtd_return = await self._calc_period_return(account_id, today.replace(day=1), today)
        ytd_return = await self._calc_period_return(account_id, today.replace(month=1, day=1), today)
        
        # 计算趋势
        trend = TrendDirection.UP if daily_return > 0 else (
            TrendDirection.DOWN if daily_return < 0 else TrendDirection.FLAT
        )
        
        pnl = PnLMetrics(
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return,
            weekly_pnl=0.0,  # TODO: 计算周盈亏金额
            weekly_return_pct=weekly_return,
            mtd_pnl=0.0,
            mtd_return_pct=mtd_return,
            ytd_pnl=0.0,
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
        
        today_snap = await self._get_snapshot(account_id, today)
        yesterday_snap = await self._get_snapshot(account_id, yesterday)
        
        if today_snap and yesterday_snap:
            prev_eq = float(yesterday_snap.total_equity)
            curr_eq = float(today_snap.total_equity)
            if prev_eq > 0:
                pnl = curr_eq - prev_eq
                return pnl, (pnl / prev_eq * 100)
        
        return 0.0, 0.0
    
    async def _calc_period_return(self, account_id: str, start: date, end: date) -> float:
        """计算期间收益率"""
        stmt = select(EquitySnapshot).where(
            and_(
                EquitySnapshot.account_id == account_id,
                EquitySnapshot.snapshot_date >= start,
                EquitySnapshot.snapshot_date <= end,
            )
        ).order_by(EquitySnapshot.snapshot_date)
        result = await self.session.execute(stmt)
        snaps = list(result.scalars().all())
        
        if len(snaps) < 2:
            return 0.0
        
        first_eq = float(snaps[0].total_equity)
        last_eq = float(snaps[-1].total_equity)
        if first_eq <= 0:
            return 0.0
        
        return (last_eq - first_eq) / first_eq * 100
    
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
                    contribution_pct=0.0, # TODO: 计算贡献占比
                    position_size=float(p.market_value),
                ))
            
            for p in opt_positions:
                all_attrs.append(PnLAttribution(
                    symbol=p.symbol,
                    contribution=float(p.unrealized_pnl or 0),
                    contribution_pct=0.0,
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
            print(f"获取盈亏归因失败: {e}")
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
            
            # TODO: 计算VaR、最大回撤等指标
            return RiskMetrics(
                risk_level=risk_level,
                var_1d=0.0,
                var_5d=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                beta=0.0,
                concentration_risk=0.0,
                greeks=greeks,
            )
        except Exception as e:
            print(f"获取风险指标失败: {e}")
            return RiskMetrics()
    
    async def _assess_risk_level(self, account_id: str) -> RiskLevel:
        """评估风险等级"""
        try:
            risk = await self._get_risk_metrics(account_id)
            return risk.risk_level
        except:
            return RiskLevel.LOW
    
    async def _get_macro_risks(self) -> List[MacroRiskAlert]:
        """获取宏观风险告警"""
        # TODO: 从宏观风险表读取
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
            status_counts = dict(result.all())
            
            generated = sum(status_counts.get(s, 0) for s in [SignalStatus.GENERATED])
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
                    signal_id=s.signal_id,
                    symbol=s.symbol,
                    signal_type=s.signal_type.value if hasattr(s.signal_type, 'value') else str(s.signal_type),
                    direction=s.direction,
                    confidence=s.confidence,
                    expected_return=s.expected_return or 0.0,
                    risk_score=s.risk_score or 0.0,
                    timestamp=s.generated_at,
                )
                for s in signals
            ]
            
            return pipeline, signal_summaries
        except Exception as e:
            print(f"获取信号管道失败: {e}")
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
            print(f"获取持仓摘要失败: {e}")
            import traceback
            traceback.print_exc()
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
        
        # TODO: 计算取消数和滑点
        return ExecutionStats(
            active_plans=active,
            executed_today=executed,
            cancelled_today=0,
            execution_rate=0.0,
            avg_slippage=0.0,
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
                symbol=p.symbol,
                plan_type=p.plan_type or "UNKNOWN",
                status=p.plan_status,
                target_price=None,  # TODO: 从plan_details提取
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
        """获取策略表现"""
        # TODO: 从策略运行记录统计
        return []
    
    # ============ 系统健康相关 ============
    async def _get_api_health(self) -> List[APIHealth]:
        """获取API健康状态"""
        # TODO: 从API监控表读取
        return []
    
    async def _count_system_alerts(self) -> int:
        """统计系统告警数"""
        # TODO: 统计API异常、系统错误等
        return 0
    
    # ============ 市场热点相关 ============
    async def _get_market_hotspots(self) -> List[MarketHotspot]:
        """获取市场热点"""
        # TODO: 从热点分析表读取
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
            todos.append(TodoItem(
                todo_type="alert",
                priority="high",
                title=f"{alert.symbol} 价格告警",
                description=f"价格触及 ${float(alert.trigger_price):.2f}",
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
