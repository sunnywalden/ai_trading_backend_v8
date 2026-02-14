"""
策略引擎 - 管理和执行12大类量化交易策略
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import Strategy, StrategyRun
from app.models.trading_signal import TradingSignal
from app.engine.strategies.bollinger_bands import BollingerBandsMeanReversion
from app.engine.strategies.pairs_trading import PairsTrading
from app.engine.strategies.breakout_momentum import BreakoutMomentum
from app.engine.strategies.golden_cross import GoldenCross
from app.engine.strategies.fama_french import FamaFrenchThreeFactor
from app.engine.strategies.momentum_quality import MomentumQuality
from app.engine.strategies.low_volatility import LowVolatility
from app.engine.strategies.tail_hedge import TailHedge
from app.engine.strategies.iron_condor import IronCondor
from app.engine.strategies.vol_arbitrage import VolatilityArbitrage
from app.engine.strategies.sector_rotation import SectorRotation
from app.engine.strategies.cta_commodities import CTACommodities


class StrategyEngine:
    """策略引擎 - 负责策略的执行和信号生成"""
    
    # 策略实现类映射
    STRATEGY_IMPLEMENTATIONS = {
        "bollinger_mean_reversion": BollingerBandsMeanReversion,
        "pairs_trading": PairsTrading,
        "breakout_momentum": BreakoutMomentum,
        "golden_cross": GoldenCross,
        "fama_french_three_factor": FamaFrenchThreeFactor,
        "momentum_quality": MomentumQuality,
        "low_volatility": LowVolatility,
        "tail_hedge": TailHedge,
        "iron_condor": IronCondor,
        "vol_arbitrage": VolatilityArbitrage,
        "sector_rotation": SectorRotation,
        "cta_commodities": CTACommodities,
    }
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def run_strategy(
        self,
        strategy: Strategy,
        user_id: str,
        account_id: str,
        universe: Optional[List[str]] = None,
    ) -> StrategyRun:
        """
        执行策略并生成交易信号
        
        Args:
            strategy: 策略对象
            user_id: 用户ID
            account_id: 账户ID
            universe: 标的池（如果为None则使用策略默认）
        
        Returns:
            StrategyRun对象
        """
        # 创建策略运行记录
        run = StrategyRun(
            id=str(uuid4()),
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            user_id=user_id,
            account_id=account_id,
            status="RUNNING",
            started_at=datetime.utcnow(),
        )
        self.session.add(run)
        await self.session.commit()
        
        try:
            # 获取策略实现类
            strategy_impl_class = self.STRATEGY_IMPLEMENTATIONS.get(strategy.id)
            if not strategy_impl_class:
                raise ValueError(f"Strategy implementation not found: {strategy.id}")
            
            # 初始化策略实现
            strategy_impl = strategy_impl_class(
                params=strategy.default_params or {},
                session=self.session,
            )
            
            # 执行策略生成信号
            signals = await strategy_impl.generate_signals(universe=universe)
            
            # 保存信号到数据库
            signal_count = 0
            for signal_data in signals:
                signal = TradingSignal(
                    id=str(uuid4()),
                    strategy_id=strategy.id,
                    strategy_run_id=run.id,
                    symbol=signal_data["symbol"],
                    direction=signal_data["direction"],
                    strength=signal_data.get("strength", 50),
                    weight=signal_data.get("weight", 1.0),
                    risk_score=signal_data.get("risk_score", 50),
                    target_price=signal_data.get("target_price"),
                    stop_loss=signal_data.get("stop_loss"),
                    metadata=signal_data.get("metadata", {}),
                    user_id=user_id,
                    account_id=account_id,
                    created_at=datetime.utcnow(),
                )
                self.session.add(signal)
                signal_count += 1
            
            # 更新运行状态
            run.status = "COMPLETED"
            run.finished_at = datetime.utcnow()
            await self.session.commit()
            
            return run
            
        except Exception as e:
            run.status = "FAILED"
            run.error_message = str(e)
            run.finished_at = datetime.utcnow()
            await self.session.commit()
            raise
    
    async def get_strategy_signals(
        self,
        strategy_id: str,
        limit: int = 50,
    ) -> List[TradingSignal]:
        """获取策略最近生成的信号"""
        stmt = (
            select(TradingSignal)
            .where(TradingSignal.strategy_id == strategy_id)
            .order_by(TradingSignal.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_strategy_performance(
        self,
        strategy_id: str,
    ) -> Dict[str, Any]:
        """
        获取策略表现统计
        
        Returns:
            包含胜率、平均收益等指标的字典
        """
        # 查询该策略的所有信号
        stmt = select(TradingSignal).where(
            TradingSignal.strategy_id == strategy_id
        )
        result = await self.session.execute(stmt)
        signals = list(result.scalars().all())
        
        if not signals:
            return {
                "total_signals": 0,
                "win_rate": 0,
                "avg_pnl_pct": 0,
                "total_pnl": 0,
            }
        
        # 计算统计指标
        total_signals = len(signals)
        winning_signals = [s for s in signals if s.is_winner is True]
        total_pnl = sum(s.pnl or 0 for s in signals)
        signals_with_pnl = [s for s in signals if s.pnl_pct is not None]
        avg_pnl_pct = (
            sum(s.pnl_pct for s in signals_with_pnl) / len(signals_with_pnl)
            if signals_with_pnl
            else 0
        )
        
        return {
            "total_signals": total_signals,
            "win_rate": len(winning_signals) / total_signals if total_signals > 0 else 0,
            "avg_pnl_pct": float(avg_pnl_pct),
            "total_pnl": float(total_pnl),
        }
