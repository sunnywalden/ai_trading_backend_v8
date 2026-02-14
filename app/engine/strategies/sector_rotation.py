"""
行业轮动策略
"""
from typing import Any, Dict, List, Optional
from app.engine.strategies.base_strategy import BaseStrategy


class SectorRotation(BaseStrategy):
    """行业轮动策略"""
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return []
