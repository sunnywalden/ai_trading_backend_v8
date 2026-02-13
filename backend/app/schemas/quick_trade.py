"""快捷交易相关 Schema"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class ExecutionMode(str, Enum):
    """执行模式"""
    IMMEDIATE = "IMMEDIATE"      # 立即市价单
    LIMIT = "LIMIT"              # 限价单
    PLAN = "PLAN"                # 创建交易计划


class PositionSizingMethod(str, Enum):
    """仓位计算方法"""
    WEIGHT = "WEIGHT"            # 按权重分配
    EQUAL = "EQUAL"              # 均等分配
    CUSTOM = "CUSTOM"            # 自定义
    RISK_BASED = "RISK_BASED"    # 基于风险


class QuickTradeRequest(BaseModel):
    """从策略结果快速创建交易信号（symbol 从路径参数获取）"""
    execution_mode: ExecutionMode = Field(default=ExecutionMode.IMMEDIATE, description="执行模式")
    
    # 交易参数（可选，不填则使用策略建议）
    override_direction: Optional[str] = Field(None, description="覆盖方向 LONG/SHORT")
    override_quantity: Optional[float] = Field(None, description="覆盖数量")
    override_price: Optional[float] = Field(None, description="覆盖价格（限价单）")
    override_stop_loss: Optional[float] = Field(None, description="覆盖止损价")
    override_take_profit: Optional[float] = Field(None, description="覆盖止盈价")
    
    # 风险控制
    risk_budget: Optional[float] = Field(None, description="风险预算（账户权益占比）", ge=0, le=1)
    
    # 备注
    notes: Optional[str] = Field(None, description="交易备注")


class BatchQuickTradeRequest(BaseModel):
    """批量快捷交易"""
    asset_symbols: List[str] = Field(..., description="选中的标的列表")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.IMMEDIATE)
    position_sizing_method: PositionSizingMethod = Field(default=PositionSizingMethod.WEIGHT)
    
    # 自定义权重（当 method=CUSTOM 时）
    custom_weights: Optional[Dict[str, float]] = Field(None, description="自定义权重分配")
    
    # 总风险预算
    total_risk_budget: float = Field(default=0.3, description="总风险预算", ge=0, le=1)
    
    notes: Optional[str] = Field(None, description="批量交易备注")


class QuickTradePreview(BaseModel):
    """快捷交易预览"""
    symbol: str
    current_price: Optional[float] = None
    
    # 策略建议
    suggested_direction: str
    suggested_action: str
    signal_strength: float
    suggested_weight: float
    
    # 计算的交易参数
    calculated_quantity: float
    calculated_stop_loss: Optional[float] = None
    calculated_take_profit: Optional[float] = None
    
    # 风险评估
    estimated_position_value: float
    estimated_position_ratio: float  # 占账户权益比例
    risk_score: float
    risk_flags: List[str] = Field(default_factory=list)
    
    # 维度分析
    signal_dimensions: Dict[str, Any] = Field(default_factory=dict)


class QuickTradeResponse(BaseModel):
    """快捷交易响应"""
    status: str = "ok"
    signal_id: Optional[str] = None
    order_id: Optional[str] = None
    message: str
    preview: Optional[QuickTradePreview] = None


class BatchQuickTradeResponse(BaseModel):
    """批量快捷交易响应"""
    status: str = "ok"
    total_signals: int
    success_count: int
    failed_count: int
    signal_ids: List[str] = Field(default_factory=list)
    failures: List[Dict[str, str]] = Field(default_factory=list)
    message: str
