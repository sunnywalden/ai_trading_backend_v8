"""
V10: 全新Dashboard数据结构
整合所有核心模块数据，提供全景式监控
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class TrendDirection(str, Enum):
    """趋势方向"""
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


# ============ 账户概览 ============
class AccountOverview(BaseModel):
    """账户概览"""
    total_equity: float = Field(0.0, description="总权益")
    cash: float = Field(0.0, description="可用现金")
    market_value: float = Field(0.0, description="市值")
    buying_power: float = Field(0.0, description="购买力")
    margin_used: float = Field(0.0, description="已用保证金")
    margin_available: float = Field(0.0, description="可用保证金")


# ============ 盈亏分析 ============
class PnLMetrics(BaseModel):
    """盈亏指标"""
    daily_pnl: float = Field(0.0, description="今日盈亏")
    daily_return_pct: float = Field(0.0, description="今日收益率%")
    weekly_pnl: float = Field(0.0, description="本周盈亏")
    weekly_return_pct: float = Field(0.0, description="本周收益率%")
    mtd_pnl: float = Field(0.0, description="本月盈亏")
    mtd_return_pct: float = Field(0.0, description="本月收益率%")
    ytd_pnl: float = Field(0.0, description="本年盈亏")
    ytd_return_pct: float = Field(0.0, description="本年收益率%")
    trend: TrendDirection = Field(TrendDirection.FLAT, description="趋势")


class PnLAttribution(BaseModel):
    """盈亏归因"""
    symbol: str
    contribution: float
    contribution_pct: float
    position_size: float


# ============ 风险指标 ============
class GreeksExposure(BaseModel):
    """Greeks敞口"""
    delta: float = 0.0
    delta_pct: float = 0.0
    gamma: float = 0.0
    gamma_pct: float = 0.0
    vega: float = 0.0
    vega_pct: float = 0.0
    theta: float = 0.0
    theta_pct: float = 0.0


class RiskMetrics(BaseModel):
    """风险指标"""
    risk_level: RiskLevel = RiskLevel.LOW
    var_1d: float = Field(0.0, description="1日VaR")
    var_5d: float = Field(0.0, description="5日VaR")
    max_drawdown: float = Field(0.0, description="最大回撤%")
    sharpe_ratio: float = Field(0.0, description="夏普比率")
    beta: float = Field(0.0, description="β系数")
    concentration_risk: float = Field(0.0, description="集中度风险%")
    greeks: GreeksExposure = GreeksExposure()


class MacroRiskAlert(BaseModel):
    """宏观风险告警"""
    event_type: str
    severity: str
    title: str
    description: str
    impact_score: float
    timestamp: datetime


# ============ 交易信号 ============
class SignalSummary(BaseModel):
    """信号摘要"""
    signal_id: str
    symbol: str
    signal_type: str
    direction: str
    confidence: float
    expected_return: float
    risk_score: float
    timestamp: datetime
    ai_insight: Optional[str] = None


class SignalPipeline(BaseModel):
    """信号管道统计"""
    generated_count: int = 0
    validated_count: int = 0
    executed_count: int = 0
    rejected_count: int = 0
    success_rate: float = 0.0


# ============ 持仓分析 ============
class PositionSummary(BaseModel):
    """持仓摘要"""
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    weight: float
    risk_score: float
    technical_score: float
    fundamental_score: float


# ============ 交易计划 ============
class TradingPlanSummary(BaseModel):
    """交易计划摘要"""
    plan_id: str
    symbol: str
    plan_type: str
    status: str
    target_price: Optional[float]
    quantity: float
    created_at: datetime
    expires_at: Optional[datetime]


class ExecutionStats(BaseModel):
    """执行统计"""
    active_plans: int = 0
    executed_today: int = 0
    cancelled_today: int = 0
    execution_rate: float = 0.0
    avg_slippage: float = 0.0


# ============ AI洞察 ============
class AIInsight(BaseModel):
    """AI洞察"""
    insight_type: str  # opportunity, warning, suggestion, info
    priority: str  # high, medium, low
    title: str
    content: str
    action_items: List[str] = []
    related_symbol: Optional[str] = None
    created_at: datetime


# ============ 策略表现 ============
class StrategyPerformance(BaseModel):
    """策略表现"""
    strategy_id: str
    strategy_name: str
    total_runs: int
    win_rate: float
    avg_return: float
    sharpe: float
    last_run_at: Optional[datetime]
    status: str


# ============ API健康 ============
class APIHealth(BaseModel):
    """API健康状态"""
    provider: str
    status: str  # healthy, degraded, down
    success_rate: float
    avg_latency_ms: float
    rate_limit_remaining: int
    rate_limit_reset_at: Optional[datetime]


# ============ 市场热点 ============
class MarketHotspot(BaseModel):
    """市场热点"""
    category: str
    topic: str
    heat_score: float
    related_symbols: List[str]
    opportunities_count: int


# ============ 待办事项 ============
class TodoItem(BaseModel):
    """待办事项"""
    todo_type: str  # alert, plan_expiring, signal_pending, risk_warning
    priority: str  # high, medium, low
    title: str
    description: str
    action_link: str
    due_at: Optional[datetime]
    created_at: datetime


# ============ 性能趋势 ============
class PerformanceTrend(BaseModel):
    """性能趋势数据点"""
    date: str
    equity: float
    pnl: float
    return_pct: float


# ============ 完整Dashboard响应 ============
class DashboardV2Response(BaseModel):
    """V2 Dashboard完整响应"""
    
    # 基础信息
    account_id: str
    timestamp: datetime
    
    # 账户概览
    account: AccountOverview
    
    # 盈亏分析
    pnl: PnLMetrics
    top_performers: List[PnLAttribution] = []
    top_losers: List[PnLAttribution] = []
    
    # 风险管理
    risk: RiskMetrics
    macro_risks: List[MacroRiskAlert] = []
    
    # 交易信号
    signal_pipeline: SignalPipeline
    pending_signals: List[SignalSummary] = []
    signal_notifications: int = 0
    
    # 持仓分析
    positions_count: int = 0
    positions_summary: List[PositionSummary] = []
    concentration_top5: float = 0.0
    
    # 交易计划
    execution_stats: ExecutionStats
    active_plans: List[TradingPlanSummary] = []
    
    # AI洞察
    ai_insights: List[AIInsight] = []
    insights_unread: int = 0
    
    # 策略表现
    top_strategies: List[StrategyPerformance] = []
    
    # 系统健康
    api_health: List[APIHealth] = []
    system_alerts: int = 0
    
    # 市场热点
    market_hotspots: List[MarketHotspot] = []
    
    # 待办事项
    todos: List[TodoItem] = []
    todos_high_priority: int = 0
    
    # 性能趋势（最近30天）
    performance_trend: List[PerformanceTrend] = []
    
    # 元数据
    refresh_interval_seconds: int = 30
    last_refresh_at: datetime


# ============ 简化版响应（用于快速刷新） ============
class DashboardQuickUpdate(BaseModel):
    """Dashboard快速更新（仅核心指标）"""
    account_id: str
    timestamp: datetime
    total_equity: float
    daily_pnl: float
    daily_return_pct: float
    risk_level: RiskLevel
    pending_signals_count: int
    todos_count: int
    system_alerts_count: int
