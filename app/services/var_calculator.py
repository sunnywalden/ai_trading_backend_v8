"""
VaR/CVaR 风险计算器

计算投资组合的风险指标：
- VaR (Value at Risk) - 在险价值
- CVaR (Conditional VaR) / ES (Expected Shortful) - 条件在险价值
- 最大回撤及持续期
- 压力测试
"""
from typing import List, Dict, Optional, Tuple, Any
from decimal import Decimal
import statistics
import math
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equity_snapshot import EquitySnapshot
from app.services.benchmark_service import BenchmarkService


class VaRCalculator:
    """VaR和风险指标计算器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.benchmark_service = BenchmarkService(session)
    
    async def calculate_var_cvar(
        self,
        account_id: str,
        confidence_level: float = 0.95,
        days: int = 252
    ) -> Dict[str, any]:
        """
        计算VaR和CVaR
        
        Args:
            account_id: 账户ID
            confidence_level: 置信度（0.95或0.99）
            days: 历史数据天数
            
        Returns:
            {
                "var_95": -0.018,  # 95%置信度VaR
                "cvar_95": -0.025,  # 95%置信度CVaR
                "var_99": -0.032,
                "var_dollar": -2300,  # 美元金额
                "interpretation": "..."
            }
        """
        # 获取历史收益率
        returns = await self._get_historical_returns(account_id, days)
        
        if not returns or len(returns) < 30:
            return {
                "error": "数据不足",
                "message": f"至少需要30天数据，当前: {len(returns)}天"
            }
        
        # 获取当前账户权益
        current_equity = await self._get_current_equity(account_id)
        
        # 计算VaR（历史模拟法）
        var_95 = self._calculate_historical_var(returns, 0.95)
        var_99 = self._calculate_historical_var(returns, 0.99)
        
        # 计算CVaR（条件VaR，即VaR以下的平均损失）
        cvar_95 = self._calculate_cvar(returns, 0.95)
        cvar_99 = self._calculate_cvar(returns, 0.99)
        
        # 转换为美元金额
        var_95_dollar = var_95 * current_equity if current_equity else 0
        cvar_95_dollar = cvar_95 * current_equity if current_equity else 0
        
        # 计算其他风险指标
        max_drawdown, dd_duration = self._calculate_max_drawdown(returns)
        volatility_annualized = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else 0
        
        return {
            "account_id": account_id,
            "calculation_date": datetime.utcnow().isoformat(),
            "current_equity": current_equity,
            
            # VaR指标
            "var_95_pct": var_95,
            "var_95_dollar": var_95_dollar,
            "var_99_pct": var_99,
            "var_99_dollar": var_99 * current_equity if current_equity else 0,
            
            # CVaR指标
            "cvar_95_pct": cvar_95,
            "cvar_95_dollar": cvar_95_dollar,
            "cvar_99_pct": cvar_99,
            
            # 其他风险指标
            "max_drawdown_pct": max_drawdown,
            "drawdown_duration_days": dd_duration,
            "volatility_annualized": volatility_annualized,
            
            # 风险等级
            "risk_level": self._assess_risk_level(var_95, max_drawdown),
            
            # 解读
            "interpretation": self._interpret_var(var_95, cvar_95, max_drawdown)
        }
    
    def _calculate_historical_var(
        self,
        returns: List[float],
        confidence_level: float
    ) -> float:
        """
        历史模拟法计算VaR
        
        Returns:
            VaR值（负数表示损失）
        """
        if not returns:
            return 0.0
        
        # 排序收益率（从小到大）
        sorted_returns = sorted(returns)
        
        # 计算分位数位置
        percentile = 1 - confidence_level  # 95%置信度 → 5%分位数
        index = int(len(sorted_returns) * percentile)
        
        # 确保索引有效
        index = max(0, min(index, len(sorted_returns) - 1))
        
        var = sorted_returns[index]
        
        return var
    
    def _calculate_cvar(
        self,
        returns: List[float],
        confidence_level: float
    ) -> float:
        """
        计算CVaR（条件VaR / 期望损失）
        
        CVaR = 超过VaR的平均损失
        
        Returns:
            CVaR值（负数表示损失）
        """
        if not returns:
            return 0.0
        
        # 先计算VaR
        var = self._calculate_historical_var(returns, confidence_level)
        
        # 找出所有低于VaR的收益率（即尾部损失）
        tail_losses = [r for r in returns if r <= var]
        
        if not tail_losses:
            return var  # 如果没有尾部损失，CVaR等于VaR
        
        # CVaR = 尾部损失的平均值
        cvar = statistics.mean(tail_losses)
        
        return cvar
    
    def _calculate_max_drawdown(
        self,
        returns: List[float]
    ) -> Tuple[float, int]:
        """
        计算最大回撤和持续期
        
        Returns:
            (max_drawdown, duration_days)
        """
        if not returns or len(returns) < 2:
            return 0.0, 0
        
        # 计算累计收益曲线
        cumulative = []
        cum_return = 1.0
        for r in returns:
            cum_return *= (1 + r)
            cumulative.append(cum_return)
        
        # 计算回撤
        max_dd = 0.0
        max_dd_duration = 0
        peak = cumulative[0]
        peak_index = 0
        
        for i, value in enumerate(cumulative):
            if value > peak:
                peak = value
                peak_index = i
            else:
                # 当前回撤
                drawdown = (value - peak) / peak
                if drawdown < max_dd:
                    max_dd = drawdown
                    max_dd_duration = i - peak_index
        
        return max_dd, max_dd_duration
    
    def _assess_risk_level(
        self,
        var_95: float,
        max_drawdown: float
    ) -> str:
        """
        评估风险等级
        
        Returns:
            LOW/MEDIUM/HIGH/CRITICAL
        """
        var_abs = abs(var_95)
        mdd_abs = abs(max_drawdown)
        
        # 综合VaR和最大回撤判断
        if var_abs < 0.015 and mdd_abs < 0.10:  # VaR<1.5%, MDD<10%
            return "LOW"
        elif var_abs < 0.025 and mdd_abs < 0.15:  # VaR<2.5%, MDD<15%
            return "MEDIUM"
        elif var_abs < 0.040 and mdd_abs < 0.25:  # VaR<4%, MDD<25%
            return "HIGH"
        else:
            return "CRITICAL"
    
    def _interpret_var(
        self,
        var_95: float,
        cvar_95: float,
        max_drawdown: float
    ) -> str:
        """生成VaR解读"""
        
        var_pct = abs(var_95) * 100
        cvar_pct = abs(cvar_95) * 100
        mdd_pct = abs(max_drawdown) * 100
        
        interpretation = f"在95%置信度下，您的投资组合在未来一个交易日内的最大损失预计不会超过 {var_pct:.2f}%。"
        
        if abs(cvar_95) > abs(var_95) * 1.5:
            interpretation += f" 需要注意的是，一旦损失超过VaR阈值，平均损失将达到 {cvar_pct:.2f}%，尾部风险较高。"
        
        if mdd_pct > 15:
            interpretation += f" 历史最大回撤为 {mdd_pct:.2f}%，建议关注仓位管理。"
        
        return interpretation
    
    async def _get_historical_returns(
        self,
        account_id: str,
        days: int
    ) -> List[float]:
        """获取历史日收益率"""
        from datetime import date
        
        period_start_date = (datetime.utcnow() - timedelta(days=days)).date()
        
        stmt = (
            select(EquitySnapshot)
            .where(
                and_(
                    EquitySnapshot.account_id == account_id,
                    EquitySnapshot.snapshot_date >= period_start_date
                )
            )
            .order_by(EquitySnapshot.snapshot_date)
        )
        
        result = await self.session.execute(stmt)
        snapshots = result.scalars().all()
        
        if not snapshots or len(snapshots) < 2:
            return []
        
        # 计算日收益率
        returns = []
        for i in range(1, len(snapshots)):
            prev_equity = float(snapshots[i-1].total_equity)
            curr_equity = float(snapshots[i].total_equity)
            
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)
        
        return returns
    
    async def _get_current_equity(self, account_id: str) -> float:
        """获取当前账户权益"""
        from sqlalchemy import desc
        
        stmt = (
            select(EquitySnapshot)
            .where(EquitySnapshot.account_id == account_id)
            .order_by(desc(EquitySnapshot.snapshot_date))
            .limit(1)
        )
        
        result = await self.session.execute(stmt)
        snapshot = result.scalars().first()
        
        if snapshot:
            return float(snapshot.total_equity)
        
        return 100000.0  # 默认值
    
    async def stress_test(
        self,
        account_id: str,
        scenario: str = "2008_crisis"
    ) -> Dict[str, Any]:
        """
        压力测试
        
        Args:
            account_id: 账户ID
            scenario: 情景（2008_crisis / 2020_covid / custom）
            
        Returns:
            压力测试结果
        """
        # 获取当前持仓
        current_equity = await self._get_current_equity(account_id)
        
        # 定义压力情景
        stress_scenarios = {
            "2008_crisis": {
                "name": "2008年金融危机",
                "market_drop": -0.37,  # 市场跌37%
                "volatility_spike": 3.0  # 波动率放大3倍
            },
            "2020_covid": {
                "name": "2020年疫情暴跌",
                "market_drop": -0.34,
                "volatility_spike": 2.5
            },
            "black_monday": {
                "name": "黑色星期一（单日暴跌）",
                "market_drop": -0.20,  # 单日跌20%
                "volatility_spike": 5.0
            }
        }
        
        scenario_config = stress_scenarios.get(scenario, stress_scenarios["2008_crisis"])
        
        # 获取当前Beta（假设组合Beta）
        # 简化处理：假设Beta = 0.8
        portfolio_beta = 0.8
        
        # 估算组合损失
        estimated_loss_pct = scenario_config["market_drop"] * portfolio_beta
        estimated_loss_dollar = estimated_loss_pct * current_equity
        
        # 估算压力情景下的VaR
        stress_var = estimated_loss_pct * scenario_config["volatility_spike"]
        
        return {
            "scenario_name": scenario_config["name"],
            "market_scenario": scenario_config["market_drop"],
            "portfolio_beta": portfolio_beta,
            "estimated_loss_pct": estimated_loss_pct,
            "estimated_loss_dollar": estimated_loss_dollar,
            "stress_var": stress_var,
            "current_equity": current_equity,
            "post_stress_equity": current_equity + estimated_loss_dollar,
            "recommendation": self._generate_stress_recommendation(estimated_loss_pct)
        }
    
    def _generate_stress_recommendation(self, loss_pct: float) -> str:
        """生成压力测试建议"""
        
        loss_abs = abs(loss_pct)
        
        if loss_abs < 0.15:
            return "当前组合在压力情景下表现稳健，风险可控。"
        elif loss_abs < 0.25:
            return "压力情景下存在一定损失风险，建议适当降低仓位或增加对冲。"
        elif loss_abs < 0.40:
            return "压力情景下损失较大，强烈建议降低风险敞口，考虑购买保护性期权。"
        else:
            return "压力情景下可能面临严重损失，建议立即大幅降低仓位！"
