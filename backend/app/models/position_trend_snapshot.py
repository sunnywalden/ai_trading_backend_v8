"""持仓日线趋势快照模型"""
import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from app.models.db import Base


class PositionTrendSnapshot(Base):
    __tablename__ = "position_trend_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False, index=True)
    timeframe = Column(String(8), default="1D", nullable=False)
    timestamp = Column(DateTime, default=func.now(), nullable=False)

    # 趋势评分
    trend_direction = Column(String(16))
    trend_strength = Column(Integer)
    trend_description = Column(String(128))

    # 指标快照
    rsi_value = Column(Float)
    rsi_status = Column(String(16))
    macd_status = Column(String(16))
    macd_signal = Column(Float)
    bollinger_position = Column(String(32))
    volume_ratio = Column(Float)

    # 支撑阻力
    support_levels = Column(Text)
    resistance_levels = Column(Text)

    # AI总结
    ai_summary = Column(Text)

    def support_levels_list(self) -> list[float]:
        if not self.support_levels:
            return []
        try:
            return json.loads(self.support_levels)
        except json.JSONDecodeError:
            return []

    def resistance_levels_list(self) -> list[float]:
        if not self.resistance_levels:
            return []
        try:
            return json.loads(self.resistance_levels)
        except json.JSONDecodeError:
            return []

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "trend_direction": self.trend_direction,
            "trend_strength": self.trend_strength,
            "trend_description": self.trend_description,
            "rsi_value": self.rsi_value,
            "rsi_status": self.rsi_status,
            "macd_status": self.macd_status,
            "macd_signal": self.macd_signal,
            "bollinger_position": self.bollinger_position,
            "volume_ratio": self.volume_ratio,
            "support_levels": self.support_levels_list(),
            "resistance_levels": self.resistance_levels_list(),
            "ai_summary": self.ai_summary,
            "timestamp": self.timestamp.isoformat(),
        }
