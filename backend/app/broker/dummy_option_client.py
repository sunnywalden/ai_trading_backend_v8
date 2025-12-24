from typing import List
from .option_client_base import OptionBrokerClient
from .models import OptionPosition, UnderlyingPosition


class DummyOptionClient(OptionBrokerClient):
    """占位实现：不返回任何仓位，适用于未配置 Tiger API 的场景"""

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        return []

    async def list_option_positions(self, account_id: str) -> List[OptionPosition]:
        return []
