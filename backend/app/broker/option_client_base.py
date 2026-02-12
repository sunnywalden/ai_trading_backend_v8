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

    async def get_account_id(self) -> str:
        """获取真实的券商账户ID"""
        ...

    async def get_account_equity(self, account_id: str) -> float:
        """获取账户权益（USD）"""
        ...

    async def place_order(self, account_id: str, order_params: dict) -> dict:
        """下单接口
        
        Args:
            account_id: 账户号
            order_params: 包含 symbol, direction, quantity, price, order_type 等
            
        Returns:
            {
                "success": bool,
                "order_id": str,
                "status": str,
                "message": str,
                "ext_order_id": str (broker内部ID)
            }
        """
        ...

    async def get_order_status(self, account_id: str, order_id: str) -> dict:
        """获取订单状态
        
        Returns:
            {
                "status": str (FILLED, CANCELLED, REJECTED, PENDING, EXECUTING),
                "filled_quantity": float,
                "avg_fill_price": float,
                "message": str
            }
        """
        ...

