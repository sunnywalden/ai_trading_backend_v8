"""技术指标数据模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger
from sqlalchemy.sql import func
from app.models.db import Base


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    timeframe = Column(String(8), default='1D')

    # 价格数据
    close_price = Column(Float)
    volume = Column(BigInteger)

    # 移动平均线
    ma_5 = Column(Float)
    ma_10 = Column(Float)
    ma_20 = Column(Float)
    ma_50 = Column(Float)
    ma_200 = Column(Float)

    # 动量指标
    rsi_14 = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_histogram = Column(Float)

    # 波动率
    atr_14 = Column(Float)
    bb_upper = Column(Float)
    bb_middle = Column(Float)
    bb_lower = Column(Float)

    # 成交量
    volume_sma_20 = Column(BigInteger)
    obv = Column(BigInteger)
