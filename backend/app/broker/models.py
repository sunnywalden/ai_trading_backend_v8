from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Greeks:
    delta: float
    gamma: float
    vega: float
    theta: float


@dataclass
class OptionContract:
    """单个期权合约的静态信息"""
    broker_symbol: str          # 券商内部合约代码 / contract_id
    underlying: str             # 标的，比如 META / TSLA / 1810.HK
    market: str                 # "US" / "HK" / "CN" ...
    right: str                  # "CALL" / "PUT"
    strike: float
    expiry: date
    multiplier: int             # 一张合约对应多少股，US 常见为 100
    currency: str               # "USD" / "HKD" 等


@dataclass
class OptionPosition:
    """账户当前持有的某个期权合约仓位"""
    contract: OptionContract
    quantity: int               # 正数=多头，负数=空头（卖出开仓）
    avg_price: float            # 开仓均价（每份合约价格，非总 notional）
    underlying_price: float     # 当前标的价格
    greeks: Greeks              # 当前 Greeks
    last_update_ts: float       # 时间戳（秒）方便做缓存


@dataclass
class UnderlyingPosition:
    """标的股票 / ETF 仓位（用于合并期权 Delta）"""
    symbol: str                 # META / TSLA / 1810.HK
    market: str
    quantity: int               # 股数
    avg_price: float
    last_price: float
    currency: str
