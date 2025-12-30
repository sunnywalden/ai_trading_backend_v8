from typing import List
from app.core.config import settings
from .option_client_base import OptionBrokerClient
from .models import OptionPosition, UnderlyingPosition


class DummyOptionClient(OptionBrokerClient):
    """占位实现：不返回任何仓位，适用于未配置 Tiger API 的场景"""

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        return []

    async def list_option_positions(self, account_id: str) -> List[OptionPosition]:
        return []

    async def get_account_id(self) -> str:
        """返回配置的账户ID"""
        return settings.TIGER_ACCOUNT

    async def get_account_equity(self, account_id: str) -> float:
        """返回模拟权益"""
        return None  # 返回 None，由调用方使用默认值

