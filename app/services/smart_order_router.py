"""
智能订单路由 (Intelligent Order Router - IOR)

根据订单大小、市场波动率、流动性自动选择最优执行策略：
- 小单：市价单（Market Order）
- 中单：限价单（Limit Order）  
- 大单：TWAP/VWAP算法交易
"""
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.benchmark_service import BenchmarkService


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "MKT"  # 市价单
    LIMIT = "LMT"  # 限价单
    TWAP = "TWAP"  # 时间加权平均价格
    VWAP = "VWAP"  # 成交量加权平均价格
    ICEBERG = "ICEBERG"  # 冰山单


class OrderUrgency(str, Enum):
    """订单紧急度"""
    LOW = "LOW"  # 低紧急度，可以慢慢执行
    NORMAL = "NORMAL"  # 正常
    HIGH = "HIGH"  # 高紧急度，需要快速成交


class SmartOrderRouter:
    """智能订单路由"""
    
    # 订单大小阈值（相对于日均成交量）
    SMALL_ORDER_THRESHOLD = 0.01  # 1% ADV -> 市价单
    MEDIUM_ORDER_THRESHOLD = 0.05  # 5% ADV -> 限价单
    LARGE_ORDER_THRESHOLD = 0.10  # 10% ADV -> TWAP/VWAP
    
    # 波动率阈值（年化）
    LOW_VOLATILITY = 0.15  # 15%
    HIGH_VOLATILITY = 0.30  # 30%
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.benchmark_service = BenchmarkService(session)
    
    async def route_order(
        self,
        symbol: str,
        quantity: int,
        side: str,  # "BUY" or "SELL"
        urgency: OrderUrgency = OrderUrgency.NORMAL,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        智能路由订单
        
        Args:
            symbol: 股票代码
            quantity: 数量
            side: 买入/卖出
            urgency: 紧急度
            account_id: 账户ID
            
        Returns:
            {
                "order_type": "LMT",
                "quantity": 100,
                "limit_price": 150.25,
                "time_in_force": "DAY",
                "algo_strategy": "TWAP",
                "execution_horizon": "4hours",
                "slippage_estimate": 0.0015,
                "reasoning": "..."
            }
        """
        # 1. 获取股票市场数据
        market_data = await self._get_market_data(symbol)
        
        if not market_data:
            # 数据不足，默认使用市价单
            return self._create_market_order(quantity, side, "数据不足，使用市价单")
        
        # 2. 计算订单占日均成交量比例
        adv_pct = self._calculate_adv_percentage(quantity, market_data)
        
        # 3. 评估市场波动率
        volatility = market_data.get("volatility", 0.20)
        
        # 4. 智能路由决策
        routing_decision = self._make_routing_decision(
            adv_pct=adv_pct,
            volatility=volatility,
            urgency=urgency,
            market_data=market_data,
            side=side
        )
        
        # 5. 生成订单参数
        order_params = self._generate_order_params(
            symbol=symbol,
            quantity=quantity,
            side=side,
            decision=routing_decision,
            market_data=market_data
        )
        
        return order_params
    
    def _make_routing_decision(
        self,
        adv_pct: float,
        volatility: float,
        urgency: OrderUrgency,
        market_data: Dict[str, Any],
        side: str
    ) -> Dict[str, Any]:
        """
        核心路由决策逻辑
        
        Returns:
            {
                "order_type": "LMT",
                "algo": None,
                "reasoning": "..."
            }
        """
        
        # 紧急度为高 → 直接市价单
        if urgency == OrderUrgency.HIGH:
            return {
                "order_type": OrderType.MARKET,
                "algo": None,
                "reasoning": "高紧急度订单，使用市价单保证快速成交"
            }
        
        # 小单 (<1% ADV) → 市价单
        if adv_pct < self.SMALL_ORDER_THRESHOLD:
            return {
                "order_type": OrderType.MARKET,
                "algo": None,
                "reasoning": f"小额订单（占ADV {adv_pct:.2%}），市场冲击有限，使用市价单"
            }
        
        # 中单 (1-5% ADV) → 限价单
        elif adv_pct < self.MEDIUM_ORDER_THRESHOLD:
            # 如果波动率较低，使用限价单；否则使用市价单
            if volatility < self.HIGH_VOLATILITY:
                return {
                    "order_type": OrderType.LIMIT,
                    "algo": None,
                    "reasoning": f"中等订单（占ADV {adv_pct:.2%}），波动率适中，使用限价单降低成本"
                }
            else:
                return {
                    "order_type": OrderType.MARKET,
                    "algo": None,
                    "reasoning": f"中等订单但波动率高({volatility:.1%})，使用市价单避免错失成交"
                }
        
        # 大单 (5-10% ADV) → TWAP或限价单
        elif adv_pct < self.LARGE_ORDER_THRESHOLD:
            if urgency == OrderUrgency.LOW:
                return {
                    "order_type": OrderType.LIMIT,
                    "algo": "TWAP",
                    "execution_horizon": "4hours",
                    "reasoning": f"较大订单（占ADV {adv_pct:.2%}），使用TWAP分批执行，降低市场冲击"
                }
            else:
                return {
                    "order_type": OrderType.LIMIT,
                    "algo": None,
                    "reasoning": f"较大订单（占ADV {adv_pct:.2%}），使用限价单"
                }
        
        # 巨单 (>10% ADV) → VWAP或冰山单
        else:
            return {
                "order_type": OrderType.LIMIT,
                "algo": "VWAP",
                "execution_horizon": "1day",
                "reasoning": f"大额订单（占ADV {adv_pct:.2%}），使用VWAP全天分批执行，最小化市场冲击"
            }
    
    def _generate_order_params(
        self,
        symbol: str,
        quantity: int,
        side: str,
        decision: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成订单参数"""
        
        order_type = decision["order_type"]
        current_price = market_data.get("last_price", 100.0)
        bid = market_data.get("bid", current_price * 0.999)
        ask = market_data.get("ask", current_price * 1.001)
        
        base_params = {
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "order_type": order_type,
            "reasoning": decision["reasoning"]
        }
        
        # 根据订单类型设置参数
        if order_type == OrderType.MARKET:
            base_params.update({
                "time_in_force": "DAY",
                "slippage_estimate": self._estimate_slippage(
                    adv_pct=self._calculate_adv_percentage(quantity, market_data),
                    volatility=market_data.get("volatility", 0.20)
                )
            })
        
        elif order_type == OrderType.LIMIT:
            # 限价单：买入时在bid上方一点，卖出时在ask下方一点
            if side == "BUY":
                limit_price = bid + (ask - bid) * 0.3  # 靠近bid，但给30%的价差空间
            else:  # SELL
                limit_price = ask - (ask - bid) * 0.3  # 靠近ask
            
            base_params.update({
                "limit_price": round(limit_price, 2),
                "time_in_force": "DAY",
                "slippage_estimate": (limit_price - current_price) / current_price if side == "BUY" else (current_price - limit_price) / current_price
            })
        
        # 算法交易参数
        if "algo" in decision and decision["algo"]:
            base_params.update({
                "algo_strategy": decision["algo"],
                "execution_horizon": decision.get("execution_horizon", "4hours"),
                "child_order_size": max(10, quantity // 20)  # 分成20份，每份至少10股
            })
        
        return base_params
    
    def _calculate_adv_percentage(
        self,
        quantity: int,
        market_data: Dict[str, Any]
    ) -> float:
        """计算订单占日均成交量的百分比"""
        
        avg_volume = market_data.get("avg_volume", 1000000)
        
        if avg_volume == 0:
            return 1.0  # 没有成交量数据，保守估计为100%
        
        return quantity / avg_volume
    
    def _estimate_slippage(
        self,
        adv_pct: float,
        volatility: float
    ) -> float:
        """
        估算滑点成本
        
        滑点 ≈ √(订单占比) × 波动率 × 市场冲击系数
        """
        # 简化的滑点模型
        market_impact_factor = 0.1  # 市场冲击系数
        
        estimated_slippage = (adv_pct ** 0.5) * volatility * market_impact_factor
        
        return estimated_slippage
    
    async def _get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取市场数据
        
        实际实现中应该调用Tiger Broker API获取实时数据
        这里返回模拟数据
        """
        # TODO: 集成Tiger Broker API
        # market_data = await self.tiger_client.get_quote(symbol)
        
        # 模拟数据
        return {
            "symbol": symbol,
            "last_price": 150.00,
            "bid": 149.95,
            "ask": 150.05,
            "avg_volume": 5_000_000,  # 日均500万股
            "volatility": 0.25,  # 25%年化波动率
            "spread": 0.10,
            "market_cap": 10_000_000_000  # 100亿市值
        }
    
    def _create_market_order(
        self,
        quantity: int,
        side: str,
        reasoning: str
    ) -> Dict[str, Any]:
        """创建市价单"""
        
        return {
            "order_type": OrderType.MARKET,
            "quantity": quantity,
            "side": side,
            "time_in_force": "DAY",
            "reasoning": reasoning,
            "slippage_estimate": 0.002  # 默认0.2%滑点
        }
    
    async def evaluate_execution_quality(
        self,
        symbol: str,
        executed_price: float,
        quantity: int,
        side: str,
        execution_time: datetime
    ) -> Dict[str, Any]:
        """
        事后评估执行质量
        
        Args:
            symbol: 股票代码
            executed_price: 实际成交价
            quantity: 成交数量
            side: 买入/卖出
            execution_time: 成交时间
            
        Returns:
            {
                "execution_quality": "GOOD",
                "slippage_actual": 0.0012,
                "vs_vwap": -0.0003,  # 相对VWAP的差异
                "score": 85,  # 0-100分
            }
        """
        # 获取对应时间的市场数据
        market_data = await self._get_market_data(symbol)
        
        if not market_data:
            return {"error": "无法获取市场数据"}
        
        benchmark_price = market_data["last_price"]
        
        # 计算实际滑点
        if side == "BUY":
            slippage_actual = (executed_price - benchmark_price) / benchmark_price
        else:
            slippage_actual = (benchmark_price - executed_price) / benchmark_price
        
        # 评分（滑点越小越好）
        slippage_abs = abs(slippage_actual)
        if slippage_abs < 0.001:  # <0.1%
            score = 95
            quality = "EXCELLENT"
        elif slippage_abs < 0.002:  # <0.2%
            score = 85
            quality = "GOOD"
        elif slippage_abs < 0.005:  # <0.5%
            score = 70
            quality = "FAIR"
        else:
            score = 50
            quality = "POOR"
        
        return {
            "execution_quality": quality,
            "score": score,
            "slippage_actual": slippage_actual,
            "benchmark_price": benchmark_price,
            "executed_price": executed_price,
            "price_improvement": -slippage_actual if side == "BUY" else slippage_actual,
            "interpretation": self._interpret_execution(quality, slippage_actual)
        }
    
    def _interpret_execution(self, quality: str, slippage: float) -> str:
        """解读执行质量"""
        
        slippage_pct = slippage * 100
        
        if quality == "EXCELLENT":
            return f"执行质量优秀！实际滑点仅{slippage_pct:.3f}%，远低于市场平均水平。"
        elif quality == "GOOD":
            return f"执行质量良好，实际滑点{slippage_pct:.3f}%，在合理范围内。"
        elif quality == "FAIR":
            return f"执行质量一般，实际滑点{slippage_pct:.3f}%，考虑优化订单策略。"
        else:
            return f"执行质量较差，实际滑点{slippage_pct:.3f}%，建议使用算法交易降低成本。"
