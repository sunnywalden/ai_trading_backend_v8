"""潜在机会模块 - API Schema

保持输出稳定、字段清晰：
- latest：获取最新一次成功扫描结果
- scan：手动触发扫描
- runs：查看最近 N 次扫描摘要
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class MacroRiskSnapshot(BaseModel):
    overall_score: Optional[int] = None
    risk_level: Optional[str] = None
    risk_summary: Optional[str] = None


class OpportunityItemView(BaseModel):
    rank: int
    symbol: str
    current_price: Optional[float] = None

    technical_score: int = Field(..., ge=0, le=100)
    fundamental_score: int = Field(..., ge=0, le=100)
    sentiment_score: int = Field(..., ge=0, le=100)
    overall_score: int = Field(..., ge=0, le=100)

    recommendation: Optional[str] = None
    reason: Optional[str] = None


class OpportunityRunView(BaseModel):
    run_id: int
    run_key: str
    status: str

    as_of: datetime
    universe_name: str
    min_score: int
    max_results: int
    force_refresh: bool

    macro_risk: MacroRiskSnapshot

    total_symbols: int
    qualified_symbols: int
    elapsed_ms: Optional[int] = None

    items: List[OpportunityItemView] = Field(default_factory=list)


class OpportunityRunSummaryView(BaseModel):
    run_id: int
    run_key: str
    status: str
    as_of: datetime
    universe_name: str
    min_score: int
    max_results: int
    total_symbols: int
    qualified_symbols: int
    elapsed_ms: Optional[int] = None

    macro_risk: MacroRiskSnapshot


class OpportunityLatestResponse(BaseModel):
    status: str = "ok"
    latest: Optional[OpportunityRunView] = None


class OpportunityRunsResponse(BaseModel):
    status: str = "ok"
    runs: List[OpportunityRunSummaryView]


class OpportunityScanRequest(BaseModel):
    universe_name: str = Field("US_LARGE_MID_TECH", description="股票池名称")
    min_score: int = Field(75, ge=0, le=100)
    max_results: int = Field(3, ge=1, le=10)
    force_refresh: bool = Field(False, description="是否强制刷新（会增加外部数据请求，可能触发限流）")

    schedule_cron: Optional[str] = Field(
        None,
        description=(
            "（可选）更新机会扫描定时任务触发时间，Linux crontab 5 段格式：'分钟 小时 日 月 周'。"
            "例如：'30 20 * * *' 表示每天 20:30。"
            "默认 20:30 的配置为 '30 20 * * *'。"
        ),
    )
    schedule_timezone: str = Field(
        "Asia/Shanghai",
        description="（可选）schedule_cron 的时区，默认 Asia/Shanghai（北京时间）。",
    )


class OpportunityScanResponse(BaseModel):
    status: str = "ok"
    run: OpportunityRunView
    notes: Optional[Dict[str, Any]] = None
