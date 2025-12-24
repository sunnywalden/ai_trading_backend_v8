from enum import Enum


class OrderIntent(str, Enum):
    STRATEGY = "STRATEGY"
    HEDGE = "HEDGE"
