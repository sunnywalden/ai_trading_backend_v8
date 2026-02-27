from app.core.config import settings
from .option_client_base import OptionBrokerClient
from .dummy_option_client import DummyOptionClient
from .tiger_option_client import TigerOptionClient

# ---------- Singleton cache ----------
_broker_instance: OptionBrokerClient | None = None
_tiger_instance: TigerOptionClient | None = None


def make_option_broker_client() -> OptionBrokerClient:
    """根据配置返回 Tiger 或 Dummy 客户端（单例，进程内复用）。

    - 如果在 .env 中配置了 TIGER_PRIVATE_KEY_PATH / TIGER_ID，则用 TigerOptionClient；
    - 否则退回 DummyOptionClient（Greeks/仓位全 0，系统仍可运行）。
    """
    global _broker_instance
    if _broker_instance is not None:
        return _broker_instance

    if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
        print(f"[BrokerFactory] Creating TigerOptionClient singleton (account={settings.TIGER_ACCOUNT})")
        _broker_instance = TigerOptionClient(
            private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
            tiger_id=settings.TIGER_ID,
            account=settings.TIGER_ACCOUNT,
        )
    else:
        print("[BrokerFactory] No Tiger API config found, using DummyOptionClient")
        _broker_instance = DummyOptionClient()

    return _broker_instance


def get_tiger_client() -> TigerOptionClient | None:
    """获取 Tiger 客户端单例实例。"""
    global _tiger_instance
    if _tiger_instance is not None:
        return _tiger_instance

    if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
        # 复用 broker 实例（如果已经是 Tiger 类型）
        broker = make_option_broker_client()
        if isinstance(broker, TigerOptionClient):
            _tiger_instance = broker
        else:
            _tiger_instance = TigerOptionClient(
                private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
                tiger_id=settings.TIGER_ID,
                account=settings.TIGER_ACCOUNT,
            )
        return _tiger_instance
    return None


# ---------- HK Symbol Helpers ----------

def is_hk_stock(symbol: str) -> bool:
    """判断是否为港股代码。
    
    规则：
    - 以 ".HK" 结尾（不区分大小写），如 "0700.HK"
    - 以 "HK" 结尾且前面是数字，如 "0700HK"
    - 纯数字且长度 ≤ 5 位，如 "700"、"00700"
    """
    s = symbol.strip().upper()
    if s.endswith(".HK"):
        return True
    if s.endswith("HK"):
        core = s[:-2]
        return core.isdigit() and 1 <= len(core) <= 5
    core = s.split(".")[0]
    return core.isdigit() and 1 <= len(core) <= 5


def normalize_hk_symbol(symbol: str) -> str:
    """将港股代码统一为 5 位零填充字符串（Tiger SDK 格式）。
    
    示例：
      "700"      -> "00700"
      "0700.HK"  -> "00700"
      "0700HK"   -> "00700"
      "00700"    -> "00700"
    """
    s = symbol.strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    elif s.endswith("HK"):
        s = s[:-2]
    return s.zfill(5)
