"""
策略基类
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession


class BaseStrategy(ABC):
    """所有策略的基类"""
    
    def __init__(self, params: Dict[str, Any], session: AsyncSession):
        self.params = params
        self.session = session
    
    @abstractmethod
    async def generate_signals(
        self,
        universe: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        生成交易信号
        
        Args:
            universe: 标的池，如果为None则使用默认池
        
        Returns:
            信号列表，每个信号是一个字典，包含：symbol, direction, strength, weight, risk_score等
        """
        pass
    
    def get_param(self, key: str, default: Any = None) -> Any:
        """获取参数值"""
        return self.params.get(key, default)
