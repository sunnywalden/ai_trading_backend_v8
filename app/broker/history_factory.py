from app.core.config import settings
from .trade_history_client_base import TradeHistoryClient
from .dummy_trade_history_client import DummyTradeHistoryClient
from .tiger_trade_history_client import TigerTradeHistoryClient


def make_trade_history_client() -> TradeHistoryClient:
    """根据配置返回 Tiger 或 Dummy 历史成交客户端。
    
    - 如果在 .env 中配置了 TIGER_PRIVATE_KEY_PATH / TIGER_ID，则用 TigerTradeHistoryClient；
    - 否则退回 DummyTradeHistoryClient（返回空列表，系统仍可运行）。
    """
    if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
        return TigerTradeHistoryClient(
            private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
            tiger_id=settings.TIGER_ID,
            account=settings.TIGER_ACCOUNT,
        )
    return DummyTradeHistoryClient()
