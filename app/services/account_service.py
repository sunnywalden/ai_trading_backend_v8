from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.broker.option_client_base import OptionBrokerClient

logger = logging.getLogger(__name__)


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
                logger.error(f" Error fetching equity from broker: {e}")
        
        # 降级：返回默认值
        return 100000.0

    async def get_account_info(self, account_id: str) -> dict:
        """获取账户详细信息 (Cash, Buying Power, etc.)"""
        if not self.broker:
            return {}
            
        try:
            # 直接通过 broker 获取 assets 信息
            from tigeropen.trade.trade_client import TradeClient
            # TigerOptionClient 暴露了 trade_client
            if hasattr(self.broker, 'trade_client'):
                assets = await self.broker._run_in_executor(
                    self.broker.trade_client.get_assets,
                    account=account_id
                )
                if assets:
                    asset = assets[0] if isinstance(assets, list) and len(assets) > 0 else assets
                    summary = getattr(asset, 'summary', None)
                    if summary:
                        return {
                            "cash": float(getattr(summary, 'cash', 0.0)),
                            "market_value": float(getattr(summary, 'market_value', 0.0)),
                            "buying_power": float(getattr(summary, 'buying_power', 0.0)),
                            "margin_used": float(getattr(summary, 'margin_used', 0.0)),
                            "margin_available": float(getattr(summary, 'margin_available', 0.0)),
                        }
        except Exception as e:
            logger.error(f" Error in get_account_info: {e}")
            
        return {}

