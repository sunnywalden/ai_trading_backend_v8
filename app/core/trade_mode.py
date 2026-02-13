from enum import Enum


class TradeMode(str, Enum):
    OFF = "OFF"
    DRY_RUN = "DRY_RUN"
    REAL = "REAL"
