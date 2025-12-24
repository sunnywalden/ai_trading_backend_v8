from typing import List, Protocol
from .models import OptionPosition, UnderlyingPosition


class OptionBrokerClient(Protocol):
    """期权敞口数据的统一接口（面向 OptionExposureService）"""

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        """列出当前股票/ETF 仓位，用于合并现货 Delta"""
        ...

    async def list_option_positions(self, account_id: str) -> List[OptionPosition]:
        """列出当前期权仓位（含 Greeks），US/HK 通用"""
        ...
