from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.broker.option_client_base import OptionBrokerClient


class AccountService:
    def __init__(self, session, broker_client: 'OptionBrokerClient' = None):
        self.session = session
        self.broker = broker_client

    async def get_equity_usd(self, account_id: str) -> float:
        """获取账户权益（USD）
        
        优先从 Tiger API 获取真实数据，如果失败则返回默认值
        """
        if self.broker:
            try:
                equity = await self.broker.get_account_equity(account_id)
                if equity is not None:
                    return float(equity)
            except Exception as e:
                print(f"[AccountService] Error fetching equity from broker: {e}")
        
        # 降级：返回默认值
        return 100000.0

