"""
性能评估与反馈系统 - 量化交易闭环的学习引擎

功能:
1. 持续监控交易表现
2. 评估信号质量和策略效果
3. 识别成功和失败模式
4. 生成反馈报告
5. 为自我优化提供数据基础
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from decimal import Decimal
import statistics

from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignal, SignalStatus, SignalPerformance
from app.models.strategy import Strategy, StrategyRun
from app.models.trade_pnl_attribution import TradePnlAttribution
from app.models.equity_snapshot import EquitySnapshot


class PerformanceAnalyzer:
    """性能分析器 - 评估交易表现和策略效果"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def evaluate_daily_performance(
        self,
        account_id: str,
        target_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        每日性能评估
        在每个交易日结束时运行,评估当天的交易表现
        """
        if not target_date:
            target_date = datetime.utcnow()
        
        date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # 1. 获取当天执行的所有信号
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.status == SignalStatus.EXECUTED,
                    TradingSignal.executed_at >= date_start,
                    TradingSignal.executed_at <= date_end
                )
            )
        )
        result = await self.session.execute(stmt)
        executed_signals = result.scalars().all()
        
        # 2. 获取当天的权益快照
        stmt = (
            select(EquitySnapshot)
            .where(
                and_(
                    EquitySnapshot.account_id == account_id,
                    EquitySnapshot.snapshot_date == target_date.date()
                )
            )
        )
        result = await self.session.execute(stmt)
        equity_snapshot = result.scalars().first()
        
        # 3. 计算关键指标
        daily_metrics = {
            "date": target_date.date().isoformat(),
            "account_id": account_id,
            "signals_executed": len(executed_signals),
            "total_equity": float(equity_snapshot.total_equity) if equity_snapshot else 0,
            "daily_pnl": float(equity_snapshot.realized_pnl) if equity_snapshot else 0,
            "daily_return": float(equity_snapshot.daily_return) if equity_snapshot else 0,
            "cumulative_return": float(equity_snapshot.cumulative_return) if equity_snapshot else 0,
        }
        
        # 4. 分析信号表现
        signal_analysis = await self._analyze_signal_batch(executed_signals)
        daily_metrics["signal_analysis"] = signal_analysis
        
        # 5. 识别最佳和最差信号
        best_signal, worst_signal = await self._find_extreme_signals(executed_signals)
        daily_metrics["best_signal"] = best_signal
        daily_metrics["worst_signal"] = worst_signal
        
        return daily_metrics
    
    async def _analyze_signal_batch(
        self,
        signals: List[TradingSignal]
    ) -> Dict[str, Any]:
        """分析一批信号的表现"""
        
        if not signals:
            return {}
        
        # 按来源分组
        by_source = {}
        for signal in signals:
            source = signal.signal_source.value
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(signal)
        
        # 按策略分组
        by_strategy = {}
        for signal in signals:
            if signal.strategy_id:
                if signal.strategy_id not in by_strategy:
                    by_strategy[signal.strategy_id] = []
                by_strategy[signal.strategy_id].append(signal)
        
        # 计算整体统计
        avg_confidence = statistics.mean([s.confidence for s in signals])
        avg_signal_strength = statistics.mean([s.signal_strength for s in signals])
        
        # 执行质量
        slippages = [s.execution_slippage for s in signals if s.execution_slippage is not None]
        avg_slippage = statistics.mean(slippages) if slippages else 0
        
        return {
            "total_signals": len(signals),
            "avg_confidence": avg_confidence,
            "avg_signal_strength": avg_signal_strength,
            "avg_slippage": avg_slippage,
            "by_source": {k: len(v) for k, v in by_source.items()},
            "by_strategy": {k: len(v) for k, v in by_strategy.items()},
        }
    
    async def _find_extreme_signals(
        self,
        signals: List[TradingSignal]
    ) -> tuple[Optional[Dict], Optional[Dict]]:
        """找出表现最好和最差的信号"""
        
        evaluated_signals = [s for s in signals if s.evaluation_score is not None]
        
        if not evaluated_signals:
            return None, None
        
        best = max(evaluated_signals, key=lambda s: s.evaluation_score)
        worst = min(evaluated_signals, key=lambda s: s.evaluation_score)
        
        best_dict = {
            "signal_id": best.signal_id,
            "symbol": best.symbol,
            "evaluation_score": best.evaluation_score,
            "actual_return": best.actual_return,
            "signal_source": best.signal_source.value,
        }
        
        worst_dict = {
            "signal_id": worst.signal_id,
            "symbol": worst.symbol,
            "evaluation_score": worst.evaluation_score,
            "actual_return": worst.actual_return,
            "signal_source": worst.signal_source.value,
        }
        
        return best_dict, worst_dict
    
    async def generate_strategy_report(
        self,
        strategy_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        生成策略性能报告
        用于评估策略的长期表现
        """
        period_start = datetime.utcnow() - timedelta(days=days)
        
        # 获取策略信息
        stmt = select(Strategy).where(Strategy.id == strategy_id)
        result = await self.session.execute(stmt)
        strategy = result.scalars().first()
        
        if not strategy:
            return {"error": "Strategy not found"}
        
        # 获取该策略生成的所有信号
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.strategy_id == strategy_id,
                    TradingSignal.generated_at >= period_start
                )
            )
        )
        result = await self.session.execute(stmt)
        signals = result.scalars().all()
        
        # 计算性能指标
        total_signals = len(signals)
        executed_signals = [s for s in signals if s.status == SignalStatus.EXECUTED]
        evaluated_signals = [s for s in signals if s.evaluation_score is not None]
        
        if not evaluated_signals:
            return {
                "strategy_id": strategy_id,
                "strategy_name": strategy.name,
                "period_days": days,
                "total_signals": total_signals,
                "message": "No evaluated signals in this period"
            }
        
        # 胜率和收益
        winning_signals = [s for s in evaluated_signals if s.actual_return and s.actual_return > 0]
        win_rate = len(winning_signals) / len(evaluated_signals)
        
        total_return = sum(s.actual_return or 0 for s in evaluated_signals)
        avg_return = total_return / len(evaluated_signals)
        
        # 平均评分
        avg_evaluation_score = statistics.mean([s.evaluation_score for s in evaluated_signals])
        
        # 信号质量
        avg_confidence = statistics.mean([s.confidence for s in signals])
        avg_signal_strength = statistics.mean([s.signal_strength for s in signals])
        
        # 执行质量
        rejection_rate = len([s for s in signals if s.status == SignalStatus.REJECTED]) / total_signals
        
        return {
            "strategy_id": strategy_id,
            "strategy_name": strategy.name,
            "period_days": days,
            "total_signals": total_signals,
            "executed_signals": len(executed_signals),
            "evaluated_signals": len(evaluated_signals),
            "win_rate": win_rate,
            "avg_return": avg_return,
            "total_return": total_return,
            "avg_evaluation_score": avg_evaluation_score,
            "avg_confidence": avg_confidence,
            "avg_signal_strength": avg_signal_strength,
            "rejection_rate": rejection_rate,
            "performance_grade": self._calculate_performance_grade(
                win_rate, avg_return, avg_evaluation_score
            )
        }
    
    def _calculate_performance_grade(
        self,
        win_rate: float,
        avg_return: float,
        avg_evaluation_score: float
    ) -> str:
        """计算性能等级 A+/A/B/C/D/F"""
        
        score = (
            win_rate * 40 +              # 胜率占40%
            min(avg_return * 100, 20) +  # 收益率最多占20%
            avg_evaluation_score * 0.4   # 评估分数占40%
        )
        
        if score >= 90:
            return "A+"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 50:
            return "D"
        else:
            return "F"
    
    async def identify_improvement_opportunities(
        self,
        account_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        识别改进机会
        分析失败模式,为优化提供依据
        """
        period_start = datetime.utcnow() - timedelta(days=days)
        
        # 获取表现不佳的信号
        stmt = (
            select(TradingSignal)
            .where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.generated_at >= period_start,
                    TradingSignal.evaluation_score.isnot(None),
                    TradingSignal.evaluation_score < 50  # 评分低于50的信号
                )
            )
            .order_by(TradingSignal.evaluation_score)
            .limit(20)
        )
        result = await self.session.execute(stmt)
        poor_signals = result.scalars().all()
        
        # 分析失败模式
        patterns = {
            "overconfident_signals": [],  # 高置信度但低表现
            "high_risk_failures": [],     # 高风险信号失败
            "execution_issues": [],        # 执行问题(高滑点)
            "timing_issues": [],          # 时机问题(持仓时间不当)
        }
        
        for signal in poor_signals:
            # 过度自信
            if signal.confidence > 0.8 and signal.evaluation_score < 40:
                patterns["overconfident_signals"].append({
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                    "confidence": signal.confidence,
                    "evaluation_score": signal.evaluation_score,
                })
            
            # 高风险失败
            if signal.risk_score and signal.risk_score > 70:
                patterns["high_risk_failures"].append({
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                    "risk_score": signal.risk_score,
                    "actual_return": signal.actual_return,
                })
            
            # 执行问题
            if signal.execution_slippage and abs(signal.execution_slippage) > 0.005:
                patterns["execution_issues"].append({
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                    "slippage": signal.execution_slippage,
                })
        
        # 生成改进建议
        recommendations = []
        
        if len(patterns["overconfident_signals"]) > 5:
            recommendations.append({
                "type": "CONFIDENCE_CALIBRATION",
                "message": "发现多个过度自信的信号,建议重新校准置信度模型",
                "priority": "HIGH",
                "affected_signals": len(patterns["overconfident_signals"])
            })
        
        if len(patterns["high_risk_failures"]) > 5:
            recommendations.append({
                "type": "RISK_ASSESSMENT",
                "message": "高风险信号失败率高,建议提高风险阈值或优化风险评估",
                "priority": "HIGH",
                "affected_signals": len(patterns["high_risk_failures"])
            })
        
        if len(patterns["execution_issues"]) > 3:
            recommendations.append({
                "type": "EXECUTION_OPTIMIZATION",
                "message": "执行滑点较大,建议优化订单执行策略或调整时机",
                "priority": "MEDIUM",
                "affected_signals": len(patterns["execution_issues"])
            })
        
        return {
            "period_days": days,
            "total_poor_performers": len(poor_signals),
            "patterns": patterns,
            "recommendations": recommendations
        }
