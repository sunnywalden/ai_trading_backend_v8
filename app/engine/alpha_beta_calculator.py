"""
Alpha/Beta 计算器 - 核心财务指标计算

基于CAPM模型计算：
- Alpha（超额收益）
- Beta（系统性风险）
- Sharpe Ratio（夏普比率）
- Information Ratio（信息比率）
"""
from typing import List, Dict, Optional
from decimal import Decimal
import statistics
import math


class AlphaBetaCalculator:
    """Alpha和Beta计算器"""
    
    @staticmethod
    def calculate_beta(
        portfolio_returns: List[float],
        benchmark_returns: List[float]
    ) -> float:
        """
        计算Beta（投资组合相对市场的系统性风险）
        
        Beta = Cov(Rp, Rm) / Var(Rm)
        
        Args:
            portfolio_returns: 投资组合日收益率序列
            benchmark_returns: 基准日收益率序列
            
        Returns:
            Beta值（通常在0.5-1.5之间）
        """
        if not portfolio_returns or not benchmark_returns:
            return 1.0  # 默认Beta=1
        
        if len(portfolio_returns) != len(benchmark_returns):
            # 长度不匹配，取最短
            min_len = min(len(portfolio_returns), len(benchmark_returns))
            portfolio_returns = portfolio_returns[-min_len:]
            benchmark_returns = benchmark_returns[-min_len:]
        
        if len(portfolio_returns) < 5:  # 样本太少
            return 1.0
        
        # 计算协方差
        portfolio_mean = statistics.mean(portfolio_returns)
        benchmark_mean = statistics.mean(benchmark_returns)
        
        covariance = sum(
            (pr - portfolio_mean) * (br - benchmark_mean)
            for pr, br in zip(portfolio_returns, benchmark_returns)
        ) / (len(portfolio_returns) - 1)
        
        # 计算基准方差
        benchmark_variance = statistics.variance(benchmark_returns)
        
        if benchmark_variance == 0:
            return 1.0
        
        beta = covariance / benchmark_variance
        
        return beta
    
    @staticmethod
    def calculate_alpha(
        portfolio_returns: List[float],
        benchmark_returns: List[float],
        risk_free_rate: float = 0.0
    ) -> float:
        """
        计算Alpha（超额收益）
        
        Alpha = Rp - [Rf + Beta * (Rm - Rf)]
        
        Args:
            portfolio_returns: 投资组合日收益率
            benchmark_returns: 基准日收益率
            risk_free_rate: 无风险利率（年化），默认0
            
        Returns:
            Alpha（日均），年化需乘以252
        """
        if not portfolio_returns or not benchmark_returns:
            return 0.0
        
        # 计算Beta
        beta = AlphaBetaCalculator.calculate_beta(portfolio_returns, benchmark_returns)
        
        # 计算平均收益率
        portfolio_mean = statistics.mean(portfolio_returns)
        benchmark_mean = statistics.mean(benchmark_returns)
        
        # 日无风险利率
        daily_rf = risk_free_rate / 252
        
        # CAPM公式
        alpha = portfolio_mean - (daily_rf + beta * (benchmark_mean - daily_rf))
        
        return alpha
    
    @staticmethod
    def calculate_sharpe_ratio(
        returns: List[float],
        risk_free_rate: float = 0.0
    ) -> float:
        """
        计算夏普比率
        
        Sharpe = (Rp - Rf) / σp
        
        Args:
            returns: 收益率序列
            risk_free_rate: 年化无风险利率
            
        Returns:
            夏普比率（已年化）
        """
        if not returns or len(returns) < 2:
            return 0.0
        
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)
        
        if std_return == 0:
            return 0.0
        
        # 日无风险利率
        daily_rf = risk_free_rate / 252
        
        # 计算夏普（日频）
        sharpe_daily = (mean_return - daily_rf) / std_return
        
        # 年化：乘以sqrt(252)
        sharpe_annualized = sharpe_daily * math.sqrt(252)
        
        return sharpe_annualized
    
    @staticmethod
    def calculate_information_ratio(
        portfolio_returns: List[float],
        benchmark_returns: List[float]
    ) -> float:
        """
        计算信息比率（衡量主动管理能力）
        
        IR = Alpha / Tracking Error
        
        Args:
            portfolio_returns: 投资组合收益率
            benchmark_returns: 基准收益率
            
        Returns:
            信息比率（已年化）
        """
        if not portfolio_returns or not benchmark_returns:
            return 0.0
        
        if len(portfolio_returns) != len(benchmark_returns):
            min_len = min(len(portfolio_returns), len(benchmark_returns))
            portfolio_returns = portfolio_returns[-min_len:]
            benchmark_returns = benchmark_returns[-min_len:]
        
        if len(portfolio_returns) < 5:
            return 0.0
        
        # 计算Alpha
        alpha = AlphaBetaCalculator.calculate_alpha(portfolio_returns, benchmark_returns)
        
        # 计算跟踪误差（Active Return的标准差）
        active_returns = [
            pr - br 
            for pr, br in zip(portfolio_returns, benchmark_returns)
        ]
        
        tracking_error = statistics.stdev(active_returns)
        
        if tracking_error == 0:
            return 0.0
        
        # IR = Alpha / TE（日频）
        ir_daily = alpha / tracking_error
        
        # 年化
        ir_annualized = ir_daily * math.sqrt(252)
        
        return ir_annualized
    
    @staticmethod
    def calculate_sortino_ratio(
        returns: List[float],
        risk_free_rate: float = 0.0,
        target_return: float = 0.0
    ) -> float:
        """
        计算Sortino比率（只考虑下行风险）
        
        Sortino = (Rp - Target) / Downside Deviation
        
        Args:
            returns: 收益率序列
            risk_free_rate: 年化无风险利率
            target_return: 目标收益率
            
        Returns:
            Sortino比率（已年化）
        """
        if not returns or len(returns) < 2:
            return 0.0
        
        mean_return = statistics.mean(returns)
        
        # 计算下行偏差（只考虑低于目标的收益）
        downside_returns = [r for r in returns if r < target_return]
        
        if not downside_returns:
            return float('inf')  # 没有下行风险
        
        downside_deviation = math.sqrt(
            sum((r - target_return) ** 2 for r in downside_returns) / len(downside_returns)
        )
        
        if downside_deviation == 0:
            return 0.0
        
        # Sortino（日频）
        daily_rf = risk_free_rate / 252
        sortino_daily = (mean_return - daily_rf) / downside_deviation
        
        # 年化
        sortino_annualized = sortino_daily * math.sqrt(252)
        
        return sortino_annualized
    
    @staticmethod
    def calculate_calmar_ratio(
        returns: List[float],
        max_drawdown: float
    ) -> float:
        """
        计算Calmar比率
        
        Calmar = Annualized Return / Max Drawdown
        
        Args:
            returns: 收益率序列
            max_drawdown: 最大回撤（正数）
            
        Returns:
            Calmar比率
        """
        if not returns or max_drawdown == 0:
            return 0.0
        
        # 年化收益
        mean_return = statistics.mean(returns)
        annualized_return = mean_return * 252
        
        # Calmar
        calmar = annualized_return / abs(max_drawdown)
        
        return calmar
