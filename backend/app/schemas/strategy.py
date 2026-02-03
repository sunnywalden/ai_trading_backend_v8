from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StrategySummaryView(BaseModel):
    id: str
    name: str
    style: Optional[str] = None
    description: Optional[str] = None
    is_builtin: bool
    is_active: bool
    tags: List[str] = Field(default_factory=list)
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None


class StrategyListResponse(BaseModel):
    status: str = "ok"
    strategies: List[StrategySummaryView] = Field(default_factory=list)


class StrategyDetailView(StrategySummaryView):
    version: int
    default_params: Dict[str, Any] = Field(default_factory=dict)
    signal_sources: Dict[str, Any] = Field(default_factory=dict)
    risk_profile: Dict[str, Any] = Field(default_factory=dict)


class StrategyDetailResponse(BaseModel):
    status: str = "ok"
    strategy: StrategyDetailView


class StrategyCreateRequest(BaseModel):
    name: str
    style: Optional[str]
    description: Optional[str]
    default_params: Dict[str, Any] = Field(default_factory=dict)
    signal_sources: Dict[str, Any] = Field(default_factory=dict)
    risk_profile: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    is_builtin: bool = Field(False)
    is_active: bool = Field(True)


class StrategyUpdateParamsRequest(BaseModel):
    default_params: Dict[str, Any]


class StrategyRunRequest(BaseModel):
    account_id: str
    budget: Optional[float] = None
    direction: Optional[str] = None
    param_overrides: Dict[str, Any] = Field(default_factory=dict)
    notify_channels: List[str] = Field(default_factory=list)
    target_universe: Optional[str] = None
    priority: Optional[int] = None


class StrategyRunResponse(BaseModel):
    status: str = "ok"
    run_id: str
    celery_task_id: Optional[str] = None


class StrategyRunStatusView(BaseModel):
    run_id: str
    status: str
    phase: Optional[str] = None
    progress: int = Field(ge=0, le=100)
    attempt: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    timeline: Optional[Dict[str, Any]] = None


class StrategyRunLatestResponse(BaseModel):
    status: str = "ok"
    run: Optional[StrategyRunStatusView] = None


class StrategyRunHistoryView(BaseModel):
    run_id: str
    strategy_id: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    hits: Optional[int] = None
    hit_rate: Optional[float] = None
    avg_signal_strength: Optional[float] = None


class StrategyRunHistoryResponse(BaseModel):
    status: str = "ok"
    runs: List[StrategyRunHistoryView] = Field(default_factory=list)


class StrategyRunAssetView(BaseModel):
    symbol: str
    signal_strength: Optional[float] = None
    weight: Optional[float] = None
    risk_flags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    signal_dimensions: Dict[str, Any] = Field(default_factory=dict)


class StrategyRunResultsResponse(BaseModel):
    status: str = "ok"
    run_id: str
    strategy_id: str
    assets: List[StrategyRunAssetView] = Field(default_factory=list)


class StrategyExportResponse(BaseModel):
    status: str = "ok"
    run_id: str
    download_url: str
    file_path: str
