"""
交易信号数据模型 - 量化交易闭环的核心

信号生命周期: GENERATED → VALIDATED → EXECUTED → EVALUATED → ARCHIVED
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, ForeignKey, Index, Text, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum

from app.models.db import Base


class SignalType(str, Enum):
    """信号类型"""
    ENTRY = "ENTRY"           # 开仓信号
    EXIT = "EXIT"             # 平仓信号
    ADD = "ADD"               # 加仓信号
    REDUCE = "REDUCE"         # 减仓信号
    HEDGE = "HEDGE"           # 对冲信号


class SignalStatus(str, Enum):
    """信号状态"""
    GENERATED = "GENERATED"       # 已生成
    VALIDATED = "VALIDATED"       # 已验证(通过风控)
    REJECTED = "REJECTED"         # 已拒绝(风控不通过)
    QUEUED = "QUEUED"            # 队列中
    EXECUTING = "EXECUTING"       # 执行中
    EXECUTED = "EXECUTED"         # 已执行
    FAILED = "FAILED"            # 执行失败
    CANCELLED = "CANCELLED"       # 已取消
    EXPIRED = "EXPIRED"          # 已过期


class SignalSource(str, Enum):
    """信号来源"""
    STRATEGY = "STRATEGY"         # 策略信号
    RESEARCH = "RESEARCH"         # 研究信号
    AI_ADVICE = "AI_ADVICE"       # AI建议
    MANUAL = "MANUAL"            # 手动信号
    RISK_MGMT = "RISK_MGMT"      # 风险管理
    ARBITRAGE = "ARBITRAGE"       # 套利


class TradingSignal(Base):
    """交易信号表 - 所有交易决策的源头"""
    __tablename__ = "trading_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 信号基本信息
    signal_id = Column(String(64), unique=True, nullable=False, index=True)  # UUID
    signal_type = Column(SQLEnum(SignalType), nullable=False)
    signal_source = Column(SQLEnum(SignalSource), nullable=False)
    status = Column(SQLEnum(SignalStatus), nullable=False, default=SignalStatus.GENERATED)
    
    # 交易标的
    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(8), nullable=False)  # LONG/SHORT
    
    # 信号强度与置信度
    signal_strength = Column(Float, nullable=False)  # 0-100: 信号强度
    confidence = Column(Float, nullable=False)       # 0-1: 置信度
    expected_return = Column(Float)                  # 预期收益率
    risk_score = Column(Float)                       # 风险评分
    
    # 交易参数
    suggested_quantity = Column(Float)               # 建议数量
    suggested_price = Column(Float)                  # 建议价格
    stop_loss = Column(Float)                        # 止损价
    take_profit = Column(Float)                      # 止盈价
    max_holding_days = Column(Integer)               # 最大持仓天数
    
    # 来源追溯
    strategy_id = Column(String(36), ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True)
    strategy_run_id = Column(String(36), ForeignKey("strategy_runs.id", ondelete="SET NULL"), nullable=True)
    research_id = Column(String(64), nullable=True)  # 研究报告ID
    factor_scores = Column(JSON)                     # 因子得分详情
    
    # 用户与账户
    account_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False)
    
    # 验证与风控
    risk_check_passed = Column(String(8))            # YES/NO/PENDING
    risk_check_details = Column(JSON)                # 风控检查详情
    validation_errors = Column(JSON)                 # 验证错误
    
    # 执行追踪
    order_id = Column(String(64), nullable=True)     # 关联订单ID
    executed_at = Column(DateTime, nullable=True)
    executed_price = Column(Float, nullable=True)
    executed_quantity = Column(Float, nullable=True)
    execution_slippage = Column(Float, nullable=True) # 滑点
    
    # 评估结果
    actual_return = Column(Float, nullable=True)     # 实际收益率
    holding_days = Column(Integer, nullable=True)
    pnl = Column(Float, nullable=True)               # 盈亏
    evaluation_score = Column(Float, nullable=True)  # 事后评分(0-100)
    evaluation_notes = Column(Text, nullable=True)
    
    # 元数据
    extra_metadata = Column(JSON)                    # 额外信息(避免与SQLAlchemy保留字冲突)
    tags = Column(JSON)                              # 标签
    priority = Column(Integer, default=50)           # 优先级(1-100)
    
    # 时间戳
    generated_at = Column(DateTime, nullable=False, server_default=func.now())
    validated_at = Column(DateTime, nullable=True)
    expired_at = Column(DateTime, nullable=True)     # 信号过期时间
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # 关系
    strategy = relationship("Strategy", lazy="selectin")
    strategy_run = relationship("StrategyRun", lazy="selectin")
    
    __table_args__ = (
        Index("ix_signals_status_priority", "status", "priority"),
        Index("ix_signals_account_status", "account_id", "status"),
        Index("ix_signals_symbol_date", "symbol", "generated_at"),
        Index("ix_signals_source_type", "signal_source", "signal_type"),
    )


class SignalPerformance(Base):
    """信号性能统计表 - 用于反馈优化"""
    __tablename__ = "signal_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 统计维度
    dimension_type = Column(String(32), nullable=False)  # strategy/source/symbol/factor
    dimension_value = Column(String(128), nullable=False)
    
    # 时间范围
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    
    # 性能指标
    total_signals = Column(Integer, default=0)
    executed_signals = Column(Integer, default=0)
    winning_signals = Column(Integer, default=0)
    losing_signals = Column(Integer, default=0)
    
    # 收益指标
    total_return = Column(Float, default=0.0)
    avg_return = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)       # 盈亏比
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    
    # 执行质量
    avg_slippage = Column(Float, default=0.0)
    avg_execution_time = Column(Float, default=0.0)  # 秒
    rejection_rate = Column(Float, default=0.0)
    
    # 信号质量
    avg_confidence = Column(Float, default=0.0)
    avg_signal_strength = Column(Float, default=0.0)
    avg_holding_days = Column(Float, default=0.0)
    
    # 元数据
    sample_size = Column(Integer, default=0)
    statistical_significance = Column(Float, default=0.0)  # p-value
    last_calculated_at = Column(DateTime, nullable=False, server_default=func.now())
    
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index("ix_perf_dimension", "dimension_type", "dimension_value"),
        Index("ix_perf_period", "period_start", "period_end"),
    )
