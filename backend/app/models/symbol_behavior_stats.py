from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, text, Index
from .db import Base


class SymbolBehaviorStats(Base):
    __tablename__ = "symbol_behavior_stats"

    __table_args__ = (
        Index("ix_behavior_account_symbol_window", "account_id", "symbol", "window_days"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    window_days = Column(Integer, nullable=False)

    # 基本统计
    trade_count = Column(Integer, nullable=False, default=0)  # 统计窗口内总成交笔数
    net_position_days = Column(Integer, nullable=False, default=0)  # 可选：持仓天数近似
    avg_holding_days = Column(DECIMAL(10, 2), nullable=False, default=0)  # 可选：平均持仓天数

    # 卖飞相关
    sell_fly_events = Column(Integer, nullable=False, default=0)  # 卖飞事件次数
    sell_fly_extra_cost_ratio = Column(DECIMAL(10, 4), nullable=False, default=0)  # 卖飞额外成本占成交额比例

    # 过度交易相关
    overtrade_index = Column(DECIMAL(10, 4), nullable=False, default=0)  # 平均每日成交笔数等近似指标

    # 报复性交易相关
    revenge_events = Column(Integer, nullable=False, default=0)  # 报复性交易事件次数

    # 追高相关（预留，当前行为评分暂未使用，可后续扩展）
    chase_high_count = Column(Integer, nullable=False, default=0)
    chase_high_loss_rate = Column(DECIMAL(10, 4), nullable=False, default=0)

    # 各维度评分
    overtrade_score = Column(Integer, nullable=False, default=0)
    revenge_trade_score = Column(Integer, nullable=False, default=0)
    behavior_score = Column(Integer, nullable=False, default=50)
    sell_fly_score = Column(Integer, nullable=False, default=50)

    updated_at = Column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
