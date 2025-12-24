from app.core.config import settings
from .option_client_base import OptionBrokerClient
from .dummy_option_client import DummyOptionClient
from .tiger_option_client import TigerOptionClient


def make_option_broker_client() -> OptionBrokerClient:
    """根据配置返回 Tiger 或 Dummy 客户端。

    - 如果在 .env 中配置了 TIGER_PRIVATE_KEY_PATH / TIGER_ID，则用 TigerOptionClient；
    - 否则退回 DummyOptionClient（Greeks/仓位全 0，系统仍可运行）。
    """
    if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
        return TigerOptionClient(
            private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
            tiger_id=settings.TIGER_ID,
            account=settings.TIGER_ACCOUNT,
        )
    return DummyOptionClient()
