"""V10: StressTestService — 历史情景压力测试"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 预定义情景：{name: {sector_shock_pct, equity_shock_pct, description}}
SCENARIOS: Dict[str, dict] = {
    "GFC_2008": {
        "equity_shock": -0.50,
        "duration_days": 365,
        "description": "2008 年金融危机，标普500下跌约 -50%",
    },
    "COVID_2020": {
        "equity_shock": -0.35,
        "duration_days": 33,
        "description": "2020 年 COVID 黑天鹅，标普500下跌约 -35%（33天）",
    },
    "RATE_HIKE_2022": {
        "equity_shock": -0.25,
        "duration_days": 365,
        "description": "2022 年激进加息周期，纳斯达克下跌超 -33%",
    },
    "FLASH_CRASH": {
        "equity_shock": -0.10,
        "duration_days": 1,
        "description": "闪崩：单日跌幅 -10%",
    },
    "TECH_SELLOFF": {
        "equity_shock": -0.40,
        "duration_days": 90,
        "description": "科技股杀估值（互联网泡沫风格），下跌 -40%",
    },
}


class StressTestService:
    """对当前持仓组合运行历史/假设情景压力测试"""

    async def run_scenarios(
        self,
        positions: Dict[str, dict],  # {symbol: {"qty": float, "price": float, "market_value": float}}
        portfolio_equity: float,
        scenario_names: Optional[List[str]] = None,
    ) -> dict:
        """
        positions: 持仓字典
        portfolio_equity: 账户净值
        scenario_names: 要运行的情景列表（None = 全部）
        返回: {scenario_name: {"pnl_usd": float, "pnl_pct": float, "over_limit": bool}, "cvar_99": float, "symbol_exposure": {...}}
        """
        selected = scenario_names or list(SCENARIOS.keys())
        total_market_value = sum(
            pos.get("market_value", pos.get("qty", 0) * pos.get("price", 0))
            for pos in positions.values()
        )

        results = {}
        pnl_values = []
        for name in selected:
            scenario = SCENARIOS.get(name)
            if not scenario:
                logger.warning(f"Unknown scenario: {name}")
                continue

            shock = scenario["equity_shock"]
            pnl_usd = total_market_value * shock
            pnl_pct = pnl_usd / portfolio_equity if portfolio_equity > 0 else 0.0
            over_limit = abs(pnl_pct) > 0.15  # MAX_STRESS_LOSS_PCT 硬编码 15%

            results[name] = {
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 4),
                "shock": shock,
                "over_limit": over_limit,
                "description": scenario["description"],
            }
            pnl_values.append(pnl_usd)

        # CVaR@99%（最坏 1% 情景的平均损失）
        if pnl_values:
            sorted_pnl = sorted(pnl_values)
            n = max(1, len(sorted_pnl) // 100)
            cvar_99 = sum(sorted_pnl[:n]) / n
        else:
            cvar_99 = 0.0

        # 各标的贡献（按仓位占比）
        symbol_exposure = {}
        for sym, pos in positions.items():
            mv = pos.get("market_value", pos.get("qty", 0) * pos.get("price", 0))
            exposure_pct = mv / portfolio_equity if portfolio_equity > 0 else 0
            symbol_exposure[sym] = {
                "market_value": round(mv, 2),
                "exposure_pct": round(exposure_pct, 4),
            }

        return {
            "scenarios": results,
            "cvar_99": round(cvar_99, 2),
            "symbol_exposure": symbol_exposure,
            "portfolio_equity": portfolio_equity,
            "total_market_value": round(total_market_value, 2),
        }

    def get_available_scenarios(self) -> List[dict]:
        return [
            {"name": k, "description": v["description"], "equity_shock": v["equity_shock"]}
            for k, v in SCENARIOS.items()
        ]


# 全局单例
stress_test_service = StressTestService()
