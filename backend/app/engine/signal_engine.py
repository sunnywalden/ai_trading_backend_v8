"""
信号引擎 - 量化交易闭环的核心组件

功能:
1. 从多个来源(策略/研究/AI)收集交易信号
2. 统一信号格式和评分
3. 信号验证和风险过滤
4. 信号优先级排序
5. 信号生命周期管理
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import uuid4
from decimal import Decimal

from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import (
    TradingSignal, SignalType, SignalStatus, SignalSource, SignalPerformance
)
from app.models.strategy import Strategy, StrategyRun, StrategyRunAsset
from app.services.risk_config_service import RiskConfigService
from app.services.safety_guard import SafetyGuard
from app.services.account_service import AccountService
from app.broker.factory import make_option_broker_client
from app.core.trade_mode import TradeMode
from app.core.cache import cache


class SignalEngine:
    """信号引擎 - 交易信号的生成、验证和管理"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.risk_svc = RiskConfigService(session)
        self.account_svc = AccountService(session)
        try:
            self.broker = make_option_broker_client()
        except Exception as e:
            print(f"初始化broker失败: {e}")
            self.broker = None
    
    async def generate_signals_from_strategy_run(
        self, 
        strategy_run_id: str,
        max_signals: int = 10
    ) -> List[TradingSignal]:
        """
        从策略运行结果生成交易信号
        这是研究到交易的桥梁
        """
        # 获取策略运行结果
        stmt = (
            select(StrategyRun)
            .where(StrategyRun.id == strategy_run_id)
        )
        result = await self.session.execute(stmt)
        strategy_run = result.scalars().first()
        
        if not strategy_run or strategy_run.status != "COMPLETED":
            return []
        
        # 获取策略资产(得分最高的标的)
        stmt = (
            select(StrategyRunAsset)
            .where(StrategyRunAsset.strategy_run_id == strategy_run_id)
            .order_by(desc(StrategyRunAsset.signal_strength))
            .limit(max_signals)
        )
        result = await self.session.execute(stmt)
        assets = result.scalars().all()
        
        signals = []
        for asset in assets:
            if asset.signal_strength < (strategy_run.min_score or 60):
                continue
            
            signal = await self._create_signal_from_asset(
                strategy_run=strategy_run,
                asset=asset
            )
            signals.append(signal)
        
        return signals
    
    async def _infer_signal_type(
        self,
        symbol: str,
        direction: str,
        account_id: str
    ) -> SignalType:
        """
        根据当前持仓智能推断信号类型
        
        规则:
        - 无持仓 → ENTRY (开仓)
        - 有同向持仓 → ADD (加仓)  
        - 有反向持仓 → EXIT (平仓/换向)
        """
        if not self.broker:
            return SignalType.ENTRY  # Broker未初始化，默认ENTRY
        
        try:
            # 获取当前持仓
            positions = await self.broker.get_stock_positions(account_id)
            
            # 查找该symbol的持仓
            position = next((p for p in positions if p.get('symbol') == symbol), None)
            
            if not position:
                return SignalType.ENTRY  # 无持仓 → 开仓
            
            position_qty = position.get('qty', 0)
            
            # 判断方向
            if position_qty > 0:  # 多头持仓
                if direction == 'LONG':
                    return SignalType.ADD  # 同向 → 加仓
                else:
                    return SignalType.EXIT  # 反向 → 平仓
            elif position_qty < 0:  # 空头持仓
                if direction == 'SHORT':
                    return SignalType.ADD  # 同向 → 加仓
                else:
                    return SignalType.EXIT  # 反向 → 平仓
            else:
                return SignalType.ENTRY  # 持仓为0 → 开仓
                
        except Exception as e:
            print(f"推断信号类型失败: {e}")
            return SignalType.ENTRY  # 错误时默认ENTRY
    
    async def _create_signal_from_asset(
        self,
        strategy_run: StrategyRun,
        asset: StrategyRunAsset
    ) -> TradingSignal:
        """从策略资产创建交易信号（含去重检查）"""
        
        # 🔍 去重检查：查找相同symbol的活跃信号
        existing_signal_stmt = (
            select(TradingSignal)
            .where(TradingSignal.symbol == asset.symbol)
            .where(TradingSignal.account_id == strategy_run.account_id)
            .where(TradingSignal.status.in_([SignalStatus.GENERATED, SignalStatus.VALIDATED]))
            .where(
                or_(
                    TradingSignal.expired_at.is_(None),
                    TradingSignal.expired_at > datetime.utcnow()
                )
            )
            .order_by(desc(TradingSignal.signal_strength))
        )
        existing_result = await self.session.execute(existing_signal_stmt)
        existing_signal = existing_result.scalars().first()
        
        new_signal_strength = asset.signal_strength or 70.0
        
        # 如果已存在信号，比较信号强度决定是否更新
        if existing_signal:
            print(f"[SignalEngine] Found existing signal for {asset.symbol}, checking update...")
            if new_signal_strength > existing_signal.signal_strength:
                # 🔄 更新为更强的信号
                signal_dims = asset.signal_dimensions or {}
                existing_signal.signal_strength = new_signal_strength
                existing_signal.confidence = min(new_signal_strength / 100.0, 1.0)
                existing_signal.expected_return = signal_dims.get('expected_return', 0.05)
                existing_signal.risk_score = signal_dims.get('risk_score', 50.0)
                existing_signal.suggested_quantity = self._calculate_position_size(
                    new_signal_strength,
                    signal_dims.get('risk_score', 50.0)
                )
                existing_signal.priority = int(new_signal_strength)
                existing_signal.strategy_run_id = strategy_run.id
                existing_signal.factor_scores = {
                    "technical_score": signal_dims.get('technical_score', 70.0),
                    "fundamental_score": signal_dims.get('fundamental_score', 70.0),
                    "momentum_score": signal_dims.get('momentum_score', 70.0),
                    "sentiment_score": signal_dims.get('sentiment_score', 70.0),
                    "signal_strength": new_signal_strength,
                }
                existing_signal.expired_at = datetime.utcnow() + timedelta(hours=24)
                
                await self.session.commit()
                await self.session.refresh(existing_signal)
                return existing_signal
            else:
                # ⏭️ 跳过较弱的信号，返回现有信号
                return existing_signal
        
        # 从signal_dimensions JSON字段提取分数,如果不存在则使用默认值
        signal_dims = asset.signal_dimensions or {}
        
        # 🧠 智能推断信号类型（基于当前持仓）
        signal_direction = strategy_run.direction or "LONG"
        signal_type = await self._infer_signal_type(
            symbol=asset.symbol,
            direction=signal_direction,
            account_id=strategy_run.account_id
        )
        
        # ✨ 创建新信号
        signal = TradingSignal(
            signal_id=str(uuid4()),
            signal_type=signal_type,
            signal_source=SignalSource.STRATEGY,
            status=SignalStatus.GENERATED,
            
            symbol=asset.symbol,
            direction=signal_direction,
            
            signal_strength=new_signal_strength,
            confidence=min(new_signal_strength / 100.0, 1.0),
            expected_return=signal_dims.get('expected_return', 0.05),
            risk_score=signal_dims.get('risk_score', 50.0),
            
            suggested_quantity=self._calculate_position_size(
                new_signal_strength,
                signal_dims.get('risk_score', 50.0)
            ),
            
            strategy_id=strategy_run.strategy_id,
            strategy_run_id=strategy_run.id,
            
            factor_scores={
                "technical_score": signal_dims.get('technical_score', 70.0),
                "fundamental_score": signal_dims.get('fundamental_score', 70.0),
                "momentum_score": signal_dims.get('momentum_score', 70.0),
                "sentiment_score": signal_dims.get('sentiment_score', 70.0),
                "signal_strength": new_signal_strength,
            },
            
            account_id=strategy_run.account_id,
            user_id=strategy_run.user_id,
            
            extra_metadata={
                "strategy_name": strategy_run.strategy.name if strategy_run.strategy else None,
                "strategy_version": strategy_run.strategy_version,
                "run_universe": strategy_run.target_universe,
            },
            
            priority=int(new_signal_strength),
            expired_at=datetime.utcnow() + timedelta(hours=24),  # 信号24小时有效
        )
        
        self.session.add(signal)
        await self.session.commit()
        await self.session.refresh(signal)
        
        return signal
    
    def _calculate_position_size(
        self, 
        signal_strength: float, 
        risk_score: float
    ) -> float:
        """
        基于信号强度和风险评分计算仓位大小
        Kelly Criterion的简化版本
        """
        # 基础仓位: 10% - 30%
        base_size = 0.10 + (signal_strength / 100.0) * 0.20
        
        # 风险调整
        risk_adjustment = 1.0 - (risk_score / 100.0) * 0.5
        
        position_size = base_size * risk_adjustment
        return max(0.05, min(0.30, position_size))  # 限制在5%-30%
    
    async def validate_signal(self, signal_id: str) -> bool:
        """
        验证信号 - 风险检查和合规性检查
        """
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return False
        
        # 检查信号是否过期
        if signal.expired_at and signal.expired_at < datetime.utcnow():
            signal.status = SignalStatus.EXPIRED
            await self.session.commit()
            return False
        
        # 风险检查
        eff_state = await self.risk_svc.get_effective_state(signal.account_id)
        
        if eff_state.effective_trade_mode == TradeMode.OFF:
            signal.status = SignalStatus.REJECTED
            signal.risk_check_passed = "NO"
            signal.risk_check_details = {"reason": "Trading mode is OFF"}
            await self.session.commit()
            return False
        
        # 使用SafetyGuard进行详细检查
        guard = SafetyGuard(signal.account_id, eff_state.limits, self.session)
        notional = (signal.suggested_price or 100.0) * (signal.suggested_quantity or 100.0)
        
        check = await guard.check_order(signal.direction, notional)
        
        if not check.allowed:
            signal.status = SignalStatus.REJECTED
            signal.risk_check_passed = "NO"
            signal.risk_check_details = {
                "reason": check.reason,
                "triggers": check.triggers
            }
            signal.validation_errors = [check.reason]
            await self.session.commit()
            return False
        
        # 验证通过
        signal.status = SignalStatus.VALIDATED
        signal.risk_check_passed = "YES"
        signal.validated_at = datetime.utcnow()
        await self.session.commit()
        
        return True
    
    async def get_pending_signals(
        self,
        account_id: Optional[str] = None,
        status: Optional[SignalStatus] = SignalStatus.VALIDATED,
        limit: int = 20
    ) -> List[TradingSignal]:
        """获取待执行的信号(按优先级排序)"""
        
        stmt = select(TradingSignal)
        
        if status:
            stmt = stmt.where(TradingSignal.status == status)
        
        if account_id:
            stmt = stmt.where(TradingSignal.account_id == account_id)
        
        # 未过期的信号
        stmt = stmt.where(
            or_(
                TradingSignal.expired_at.is_(None),
                TradingSignal.expired_at > datetime.utcnow()
            )
        )
        
        # 按优先级和时间排序
        stmt = stmt.order_by(
            desc(TradingSignal.priority),
            TradingSignal.generated_at
        ).limit(limit)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def update_signal_execution(
        self,
        signal_id: str,
        order_id: str,
        executed_price: float,
        executed_quantity: float
    ) -> None:
        """更新信号执行状态"""
        
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return
        
        signal.status = SignalStatus.EXECUTED
        signal.order_id = order_id
        signal.executed_at = datetime.utcnow()
        signal.executed_price = executed_price
        signal.executed_quantity = executed_quantity
        
        # 计算滑点
        if signal.suggested_price:
            slippage = (executed_price - signal.suggested_price) / signal.suggested_price
            signal.execution_slippage = slippage
        
        await self.session.commit()
    
    async def evaluate_signal_performance(
        self,
        signal_id: str,
        actual_return: float,
        pnl: float,
        holding_days: int
    ) -> None:
        """评估信号表现 - 用于反馈优化"""
        
        stmt = select(TradingSignal).where(TradingSignal.signal_id == signal_id)
        result = await self.session.execute(stmt)
        signal = result.scalars().first()
        
        if not signal:
            return
        
        signal.actual_return = actual_return
        signal.pnl = pnl
        signal.holding_days = holding_days
        
        # 计算评分(0-100)
        evaluation_score = self._calculate_evaluation_score(
            expected_return=signal.expected_return or 0,
            actual_return=actual_return,
            signal_strength=signal.signal_strength,
            holding_days=holding_days,
            max_holding_days=signal.max_holding_days or 30
        )
        
        signal.evaluation_score = evaluation_score
        
        # 生成评估说明
        if actual_return >= (signal.expected_return or 0):
            signal.evaluation_notes = f"Signal performed well: actual {actual_return:.2%} vs expected {signal.expected_return:.2%}"
        else:
            signal.evaluation_notes = f"Signal underperformed: actual {actual_return:.2%} vs expected {signal.expected_return:.2%}"
        
        await self.session.commit()
    
    def _calculate_evaluation_score(
        self,
        expected_return: float,
        actual_return: float,
        signal_strength: float,
        holding_days: int,
        max_holding_days: int
    ) -> float:
        """
        计算信号评估分数
        考虑: 预期vs实际收益、信号强度准确性、持仓时间效率
        """
        # 收益准确性(0-50分)
        if expected_return != 0:
            return_accuracy = 1.0 - abs(actual_return - expected_return) / abs(expected_return)
            return_score = max(0, return_accuracy * 50)
        else:
            return_score = 25 if actual_return > 0 else 0
        
        # 绝对收益(0-30分)
        absolute_score = min(30, max(0, actual_return * 100 * 3))
        
        # 时间效率(0-20分)
        if max_holding_days > 0:
            time_efficiency = 1.0 - (holding_days / max_holding_days)
            time_score = max(0, time_efficiency * 20)
        else:
            time_score = 10
        
        total_score = return_score + absolute_score + time_score
        return min(100, max(0, total_score))
    
    async def calculate_performance_stats(
        self,
        dimension_type: str,
        dimension_value: str,
        days: int = 30
    ) -> Optional[SignalPerformance]:
        """
        计算特定维度的信号性能统计
        dimension_type: 'strategy', 'source', 'symbol', 'factor'
        """
        period_start = datetime.utcnow() - timedelta(days=days)
        period_end = datetime.utcnow()
        
        # 构建查询
        stmt = select(TradingSignal).where(
            and_(
                TradingSignal.generated_at >= period_start,
                TradingSignal.generated_at <= period_end
            )
        )
        
        if dimension_type == "strategy":
            stmt = stmt.where(TradingSignal.strategy_id == dimension_value)
        elif dimension_type == "source":
            stmt = stmt.where(TradingSignal.signal_source == dimension_value)
        elif dimension_type == "symbol":
            stmt = stmt.where(TradingSignal.symbol == dimension_value)
        
        result = await self.session.execute(stmt)
        signals = result.scalars().all()
        
        if not signals:
            return None
        
        # 计算统计指标
        total_signals = len(signals)
        executed_signals = sum(1 for s in signals if s.status == SignalStatus.EXECUTED)
        
        # 只统计已评估的信号
        evaluated_signals = [s for s in signals if s.evaluation_score is not None]
        
        if not evaluated_signals:
            return None
        
        winning_signals = sum(1 for s in evaluated_signals if s.actual_return and s.actual_return > 0)
        losing_signals = sum(1 for s in evaluated_signals if s.actual_return and s.actual_return <= 0)
        
        total_return = sum(s.actual_return or 0 for s in evaluated_signals)
        avg_return = total_return / len(evaluated_signals) if evaluated_signals else 0
        win_rate = winning_signals / len(evaluated_signals) if evaluated_signals else 0
        
        # 创建或更新性能记录
        perf = SignalPerformance(
            dimension_type=dimension_type,
            dimension_value=dimension_value,
            period_start=period_start,
            period_end=period_end,
            total_signals=total_signals,
            executed_signals=executed_signals,
            winning_signals=winning_signals,
            losing_signals=losing_signals,
            total_return=total_return,
            avg_return=avg_return,
            win_rate=win_rate,
            avg_confidence=sum(s.confidence for s in signals) / total_signals,
            avg_signal_strength=sum(s.signal_strength for s in signals) / total_signals,
            sample_size=len(evaluated_signals),
            last_calculated_at=datetime.utcnow()
        )
        
        self.session.add(perf)
        await self.session.commit()
        await self.session.refresh(perf)
        
        return perf
