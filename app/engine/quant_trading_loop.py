"""
量化交易闭环协调器 - 整合所有组件

完整闭环流程:
1. Research → 策略运行产生研究结果
2. Signal → 研究结果转化为交易信号
3. Validation → 信号验证和风险过滤
4. Execution → 自动执行交易
5. Monitoring → 持续监控交易表现
6. Evaluation → 评估信号和策略效果
7. Feedback → 识别改进机会
8. Optimization → 自动优化参数
9. Loop → 循环回到Research

这是一个自我进化的量化交易系统
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import uuid4

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading_signal import TradingSignal
from app.models.strategy import Strategy
from app.engine.signal_engine import SignalEngine
from app.engine.order_executor import OrderExecutor
from app.engine.performance_analyzer import PerformanceAnalyzer
from app.engine.adaptive_optimizer import AdaptiveOptimizer
from app.services.strategy_service import StrategyRunService
from app.core.trade_mode import TradeMode
from app.core.config import settings


class QuantTradingLoop:
    """量化交易闭环协调器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.signal_engine = SignalEngine(session)
        self.order_executor = OrderExecutor(session)
        self.performance_analyzer = PerformanceAnalyzer(session)
        self.optimizer = AdaptiveOptimizer(session)
        self.strategy_run_svc = StrategyRunService(session)
    
    async def run_full_cycle(
        self,
        account_id: str,
        execute_trades: bool = True,
        optimize: bool = True
    ) -> Dict[str, Any]:
        """
        运行完整的交易闭环周期
        这是系统的核心方法,定期运行(如每日)
        """
        cycle_results = {
            "cycle_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "account_id": account_id,
            "phases": {}
        }
        
        # Phase 1: 信号生成
        print("📊 Phase 1: Signal Generation...")
        signal_phase = await self._phase_1_signal_generation(account_id)
        cycle_results["phases"]["signal_generation"] = signal_phase
        
        # Phase 2: 信号验证
        print("✅ Phase 2: Signal Validation...")
        validation_phase = await self._phase_2_signal_validation(account_id)
        cycle_results["phases"]["signal_validation"] = validation_phase
        
        # Phase 3: 交易执行
        if execute_trades:
            print("⚡ Phase 3: Trade Execution...")
            execution_phase = await self._phase_3_trade_execution(account_id)
            cycle_results["phases"]["trade_execution"] = execution_phase
        
        # Phase 4: 性能评估
        print("📈 Phase 4: Performance Evaluation...")
        evaluation_phase = await self._phase_4_performance_evaluation(account_id)
        cycle_results["phases"]["performance_evaluation"] = evaluation_phase
        
        # Phase 5: 自动优化
        if optimize:
            print("🔧 Phase 5: Adaptive Optimization...")
            optimization_phase = await self._phase_5_adaptive_optimization(account_id)
            cycle_results["phases"]["adaptive_optimization"] = optimization_phase
        
        print("✨ Full cycle completed!")
        
        return cycle_results

    async def _trigger_runtime_strategy_scan(self, account_id: str) -> Dict[str, Any]:
        """在每轮闭环开始前触发一次按时段自动市场池的策略扫描。"""
        try:
            from app.jobs.strategy_jobs import execute_strategy_run_job, AUTO_UNIVERSE_KEY

            strategy_stmt = (
                select(Strategy)
                .where(Strategy.is_active.is_(True))
                .order_by(desc(Strategy.is_builtin), desc(Strategy.updated_at))
                .limit(1)
            )
            strategy_res = await self.session.execute(strategy_stmt)
            strategy = strategy_res.scalars().first()
            if not strategy:
                return {
                    "triggered": False,
                    "reason": "NO_ACTIVE_STRATEGY",
                }

            run = await self.strategy_run_svc.create_run(
                strategy=strategy,
                user_id=account_id,
                account_id=account_id,
                direction="LONG",
                target_universe=AUTO_UNIVERSE_KEY,
                min_score=60,
                max_results=30,
                priority=10,
            )

            await execute_strategy_run_job(run.id, task_id=f"auto_cycle:{run.id}")
            return {
                "triggered": True,
                "run_id": run.id,
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "target_universe": AUTO_UNIVERSE_KEY,
            }
        except Exception as e:
            return {
                "triggered": False,
                "reason": "TRIGGER_FAILED",
                "error": str(e),
            }
    
    async def _phase_1_signal_generation(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """阶段1: 从策略运行结果生成交易信号（多策略融合）"""

        runtime_scan = await self._trigger_runtime_strategy_scan(account_id)
        
        # 获取最近完成的策略运行（改为3个，增加多样性）
        from app.models.strategy import StrategyRun
        from sqlalchemy import select, desc, and_
        
        stmt = (
            select(StrategyRun)
            .where(
                and_(
                    StrategyRun.account_id == account_id,
                    StrategyRun.status == "COMPLETED"
                )
            )
            .order_by(desc(StrategyRun.finished_at))
            .limit(3)  # ← 改为3个策略，提高多样性
        )
        
        result = await self.session.execute(stmt)
        recent_runs = result.scalars().all()
        
        all_signals = []
        signals_by_strategy = {}
        strategy_runs_used = []
        
        # 从多个策略运行生成信号
        for run in recent_runs:
            # 从策略运行生成信号
            signals = await self.signal_engine.generate_signals_from_strategy_run(
                strategy_run_id=run.id,
                max_signals=10
            )
            
            strategy_name = run.strategy.name if run.strategy else "Unknown"
            signals_by_strategy[strategy_name] = len(signals)
            all_signals.extend(signals)
            strategy_runs_used.append({
                "run_id": run.id,
                "strategy_id": run.strategy_id,
                "strategy_name": strategy_name,
                "strategy_version": run.strategy_version,
                "target_universe": run.target_universe,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "signals_generated": len(signals),
            })
        
        # 多策略信号去重和聚合（保留每个symbol置信度最高的信号）
        deduplicated_signals = self._deduplicate_signals_by_symbol(all_signals)
        
        total_signals = len(deduplicated_signals)
        
        return {
            "status": "completed",
            "total_signals_generated": total_signals,
            "signals_before_dedup": len(all_signals),
            "signals_by_strategy": signals_by_strategy,
            "strategy_runs_processed": len(recent_runs),
            "strategy_scope_note": "最近 3 个 COMPLETED 策略运行（按 finished_at 倒序）",
            "strategy_runs_used": strategy_runs_used,
            "runtime_scan": runtime_scan,
        }
    
    def _deduplicate_signals_by_symbol(
        self,
        signals: List[TradingSignal]
    ) -> List[TradingSignal]:
        """
        跨策略信号去重：每个symbol只保留置信度最高的信号
        
        Args:
            signals: 信号列表
            
        Returns:
            去重后的信号列表
        """
        if not signals:
            return []
        
        # 按symbol分组
        by_symbol = {}
        for signal in signals:
            symbol = signal.symbol
            if symbol not in by_symbol:
                by_symbol[symbol] = []
            by_symbol[symbol].append(signal)
        
        # 每个symbol保留置信度最高的
        deduplicated = []
        for symbol, symbol_signals in by_symbol.items():
            best_signal = max(symbol_signals, key=lambda s: s.confidence * s.signal_strength)
            deduplicated.append(best_signal)
        
        return deduplicated
    
    async def _phase_2_signal_validation(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """阶段2: 验证生成的信号"""
        
        from app.models.trading_signal import SignalStatus
        
        # 获取待验证的信号
        pending_signals = await self.signal_engine.get_pending_signals(
            account_id=account_id,
            status=SignalStatus.GENERATED,
            limit=50
        )
        
        validated_count = 0
        rejected_count = 0
        
        for signal in pending_signals:
            is_valid = await self.signal_engine.validate_signal(signal.signal_id)
            if is_valid:
                validated_count += 1
            else:
                rejected_count += 1
        
        return {
            "status": "completed",
            "total_signals_checked": len(pending_signals),
            "validated_signals": validated_count,
            "rejected_signals": rejected_count,
            "validation_rate": validated_count / len(pending_signals) if pending_signals else 0
        }
    
    async def _phase_3_trade_execution(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """
        阶段3: 执行已验证的交易信号。

        【架构说明】统一走 AutonomousEngine.run_decision_cycle() 作为唯一执行路径：
        - 包含 AI 二次推理、RiskGate 检查、自主级别判断、审计日志
        - 避免 QuantTradingLoop 和 run_autonomous_decision_cycle 双路径竞争
        - OrderExecutor 仅作为底层 Broker 适配器，不直接被此处调用
        """
        from app.services.autonomous_engine import autonomous_engine

        results = await autonomous_engine.run_decision_cycle(
            account_id=account_id,
            db=self.session
        )

        executed = sum(1 for r in results if r.get("order_id"))
        blocked  = sum(1 for r in results if not r.get("gate_passed"))
        cb       = any(r.get("circuit_breaker") for r in results)

        return {
            "status": "completed",
            "decisions": len(results),
            "executed_orders": executed,
            "blocked_by_risk": blocked,
            "circuit_breaker": cb,
            "execution_details": results,
        }
    
    async def _phase_4_performance_evaluation(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """阶段4: 评估交易表现"""
        
        # 每日性能评估
        daily_performance = await self.performance_analyzer.evaluate_daily_performance(
            account_id=account_id
        )
        
        # 识别改进机会
        opportunities = await self.performance_analyzer.identify_improvement_opportunities(
            account_id=account_id,
            days=30
        )
        
        return {
            "status": "completed",
            "daily_metrics": daily_performance,
            "improvement_opportunities": opportunities.get("recommendations", []),
            "poor_performers_count": opportunities.get("total_poor_performers", 0)
        }
    
    async def _phase_5_adaptive_optimization(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """阶段5: 自适应优化"""
        
        # 运行每日优化
        optimization_results = await self.optimizer.run_daily_optimization(
            account_id=account_id
        )
        
        return {
            "status": "completed",
            "optimizations_count": len(optimization_results.get("optimizations", [])),
            "optimization_details": optimization_results.get("optimizations", [])
        }
    
    async def run_strategy_research_cycle(
        self,
        account_id: str,
        strategy_id: str
    ) -> Dict[str, Any]:
        """
        运行单个策略的研究→交易周期
        用于测试新策略或进行专项研究
        """
        # 1. 运行策略
        from app.services.strategy_service import StrategyService
        strategy_svc = StrategyService(self.session)
        
        strategy = await strategy_svc.get_strategy(strategy_id)
        if not strategy:
            return {"error": "Strategy not found"}
        
        # 创建策略运行(这里简化,实际需要完整的策略执行逻辑)
        run = await self.strategy_run_svc.create_run(
            strategy=strategy,
            user_id=settings.TIGER_ACCOUNT,
            account_id=account_id,
            direction="LONG",
            max_results=10
        )
        
        # 2. 生成信号
        signals = await self.signal_engine.generate_signals_from_strategy_run(
            strategy_run_id=run.id
        )
        
        # 3. 验证信号
        validated_signals = []
        for signal in signals:
            if await self.signal_engine.validate_signal(signal.signal_id):
                validated_signals.append(signal)
        
        return {
            "strategy_id": strategy_id,
            "strategy_name": strategy.name,
            "run_id": run.id,
            "signals_generated": len(signals),
            "signals_validated": len(validated_signals),
            "top_signals": [
                {
                    "symbol": s.symbol,
                    "signal_strength": s.signal_strength,
                    "confidence": s.confidence,
                    "expected_return": s.expected_return
                }
                for s in sorted(validated_signals, key=lambda x: x.signal_strength, reverse=True)[:3]
            ]
        }
    
    async def get_loop_status(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """获取闭环系统状态"""
        
        # 🛡️ 移除同步阻塞的订单同步 logic，避免 API 超时
        # 实际同步由后台 Job 或用户显式触发执行
            
        from app.models.trading_signal import TradingSignal, SignalStatus
        from sqlalchemy import select, func, and_
        
        status_counts = {}
        for status in SignalStatus:
            stmt = select(func.count()).select_from(TradingSignal).where(
                and_(
                    TradingSignal.account_id == account_id,
                    TradingSignal.status == status
                )
            )
            result = await self.session.execute(stmt)
            status_counts[status.value] = result.scalar()
        
        return {
            "account_id": account_id,
            "system_status": "ACTIVE",
            "signal_pipeline": status_counts,
            "last_cycle": datetime.utcnow().isoformat(),
            "next_cycle": (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
