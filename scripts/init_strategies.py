"""
初始化策略库 - 创建12个内置策略
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.strategy import Strategy
from app.models.db import get_session


BUILTIN_STRATEGIES = [
    {
        "id": "bollinger_mean_reversion",
        "name": "布林带均值回归",
        "style": "均值回归",
        "description": "基于布林带的超买超卖信号，适合震荡市场",
        "is_builtin": True,
        "is_active": True,
        "default_params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "volume_threshold": 1000000
        },
        "signal_sources": ["technical", "price"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.05,
            "适用市场环境": "震荡市"
        },
        "tags": ["technical", "mean_reversion", "bollinger"]
    },
    {
        "id": "pairs_trading",
        "name": "配对交易",
        "style": "均值回归",
        "description": "基于协整关系的统计套利策略",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "lookback_days": 60,
            "z_score_threshold_long": -2.0,
            "z_score_threshold_short": 2.0
        },
        "signal_sources": ["statistical", "price"],
        "risk_profile": {
            "risk_level": "low",
            "max_position_size": 0.03,
            "适用市场环境": "震荡市"
        },
        "tags": ["statistical_arbitrage", "pairs", "mean_reversion"]
    },
    {
        "id": "breakout_momentum",
        "name": "突破动量",
        "style": "趋势跟踪",
        "description": "价格突破历史高点配合成交量确认",
        "is_builtin": True,
        "is_active": True,
        "default_params": {
            "lookback_days": 20,
            "volume_multiplier": 1.5,
            "atr_multiplier": 2.0
        },
        "signal_sources": ["technical", "volume", "price"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.04,
            "适用市场环境": "牛市"
        },
        "tags": ["momentum", "breakout", "trend_following"]
    },
    {
        "id": "golden_cross",
        "name": "黄金交叉",
        "style": "趋势跟踪",
        "description": "50日均线上穿200日均线的经典趋势策略",
        "is_builtin": True,
        "is_active": True,
        "default_params": {
            "short_period": 50,
            "long_period": 200,
            "volume_confirm": True
        },
        "signal_sources": ["technical", "trend"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.06,
            "适用市场环境": "牛市"
        },
        "tags": ["moving_average", "golden_cross", "trend"]
    },
    {
        "id": "fama_french_three_factor",
        "name": "Fama-French三因子",
        "style": "多因子",
        "description": "市场、规模、价值三因子选股模型",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "lookback_period": 252,
            "rebalance_frequency": "monthly",
            "top_percentile": 20
        },
        "signal_sources": ["fundamental", "factor"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.05,
            "适用市场环境": "全市场"
        },
        "tags": ["factor", "fundamental", "academic"]
    },
    {
        "id": "momentum_quality",
        "name": "动量+质量因子",
        "style": "多因子",
        "description": "结合价格动量和财务质量的双因子模型",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "momentum_lookback": 126,
            "quality_metrics": ["roe", "debt_ratio", "fcf_yield"],
            "momentum_weight": 0.6,
            "quality_weight": 0.4
        },
        "signal_sources": ["fundamental", "technical", "factor"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.05,
            "适用市场环境": "牛市"
        },
        "tags": ["momentum", "quality", "factor"]
    },
    {
        "id": "low_volatility",
        "name": "低波动率",
        "style": "防御",
        "description": "选择低Beta低波动率的防御性组合",
        "is_builtin": True,
        "is_active": True,
        "default_params": {
            "max_beta": 0.6,
            "max_volatility": 0.15,
            "lookback_days": 252,
            "top_n": 10
        },
        "signal_sources": ["statistical", "risk"],
        "risk_profile": {
            "risk_level": "low",
            "max_position_size": 0.1,
            "适用市场环境": "震荡市/熊市"
        },
        "tags": ["low_volatility", "defensive", "beta"]
    },
    {
        "id": "tail_hedge",
        "name": "尾部对冲",
        "style": "防御",
        "description": "通过VIX期权对冲极端风险",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "vix_threshold": 20,
            "hedge_ratio": 0.02,
            "option_type": "call"
        },
        "signal_sources": ["volatility", "risk"],
        "risk_profile": {
            "risk_level": "low",
            "max_position_size": 0.02,
            "适用市场环境": "震荡市"
        },
        "tags": ["hedge", "vix", "tail_risk"]
    },
    {
        "id": "iron_condor",
        "name": "铁鹰期权",
        "style": "波动率",
        "description": "卖出跨式期权赚取时间价值",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "dte_range": [30, 45],
            "delta_short_call": 0.16,
            "delta_short_put": -0.16,
            "spread_width": 5
        },
        "signal_sources": ["option", "volatility"],
        "risk_profile": {
            "risk_level": "high",
            "max_position_size": 0.03,
            "适用市场环境": "震荡市/低波环境"
        },
        "tags": ["options", "premium_selling", "iron_condor"]
    },
    {
        "id": "vol_arbitrage",
        "name": "波动率套利",
        "style": "波动率",
        "description": "隐含波动率与实际波动率的价差交易",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "lookback_period": 30,
            "iv_rv_threshold": 0.2,
            "hedge_delta": True
        },
        "signal_sources": ["option", "volatility"],
        "risk_profile": {
            "risk_level": "high",
            "max_position_size": 0.03,
            "适用市场环境": "高波环境"
        },
        "tags": ["volatility", "options", "arbitrage"]
    },
    {
        "id": "sector_rotation",
        "name": "行业轮动",
        "style": "宏观对冲",
        "description": "基于经济周期的行业配置策略",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "indicator_set": ["gdp_growth", "unemployment", "interest_rate"],
            "rebalance_frequency": "monthly",
            "top_sectors": 3
        },
        "signal_sources": ["macro", "sector"],
        "risk_profile": {
            "risk_level": "medium",
            "max_position_size": 0.15,
            "适用市场环境": "全市场"
        },
        "tags": ["sector", "rotation", "macro"]
    },
    {
        "id": "cta_commodities",
        "name": "CTA商品趋势",
        "style": "宏观对冲",
        "description": "商品期货的趋势跟踪策略",
        "is_builtin": True,
        "is_active": False,
        "default_params": {
            "lookback_short": 20,
            "lookback_long": 60,
            "commodities": ["GC", "CL", "SI", "HG"],
            "position_sizing": "volatility_scaled"
        },
        "signal_sources": ["price", "trend", "futures"],
        "risk_profile": {
            "risk_level": "high",
            "max_position_size": 0.05,
            "适用市场环境": "趋势市"
        },
        "tags": ["cta", "commodities", "futures", "trend"]
    }
]


async def init_strategies():
    """初始化策略数据库"""
    async for session in get_session():
        try:
            for strategy_data in BUILTIN_STRATEGIES:
                strategy = Strategy(**strategy_data)
                session.add(strategy)
            
            await session.commit()
            print(f"Successfully initialized {len(BUILTIN_STRATEGIES)} strategies")
            
        except Exception as e:
            print(f"Error initializing strategies: {e}")
            await session.rollback()
            raise
        finally:
            break


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_strategies())
