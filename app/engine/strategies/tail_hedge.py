"""
尾部对冲策略
"""
from typing import Any, Dict, List, Optional
from app.engine.strategies.base_strategy import BaseStrategy


class TailHedge(BaseStrategy):
    """尾部对冲策略"""
    
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return []
