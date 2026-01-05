from typing import List
from app.core.config import settings
from .option_client_base import OptionBrokerClient
from .models import OptionPosition, UnderlyingPosition


class DummyOptionClient(OptionBrokerClient):
    """模拟实现：返回示例持仓数据，适用于未配置 Tiger API 的场景"""

    async def list_underlying_positions(self, account_id: str) -> List[UnderlyingPosition]:
        """返回模拟的股票持仓数据"""
        # 返回一些典型的科技股持仓，便于演示和测试
        return [
            UnderlyingPosition(
                symbol="AAPL",
                market="US",
                quantity=100,
                avg_price=150.50,
                last_price=245.80,
                currency="USD"
            ),
            UnderlyingPosition(
                symbol="MSFT",
                market="US",
                quantity=50,
                avg_price=280.00,
                last_price=420.50,
                currency="USD"
            ),
            UnderlyingPosition(
                symbol="GOOGL",
                market="US",
                quantity=75,
                avg_price=120.00,
                last_price=175.30,
                currency="USD"
            ),
            UnderlyingPosition(
                symbol="NVDA",
                market="US",
                quantity=30,
                avg_price=450.00,
                last_price=880.75,
                currency="USD"
            ),
            UnderlyingPosition(
                symbol="TSLA",
                market="US",
                quantity=40,
                avg_price=200.00,
                last_price=342.80,
                currency="USD"
            )
        ]

    async def list_option_positions(self, account_id: str) -> List[OptionPosition]:
        """返回空的期权持仓列表（演示环境不涉及期权）"""
        return []

    async def get_account_id(self) -> str:
        """返回配置的账户ID或默认ID"""
        return settings.TIGER_ACCOUNT or "DEMO_ACCOUNT"

    async def get_account_equity(self, account_id: str) -> float:
        """返回模拟账户权益"""
        return 150000.0  # 15万美元模拟账户

