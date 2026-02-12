"""V9: Trade Journal schemas"""
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class JournalCreateRequest(BaseModel):
    symbol: str
    direction: str
    entry_date: Optional[date] = None
    exit_date: Optional[date] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    quantity: Optional[float] = None
    realized_pnl: Optional[float] = None
    plan_id: Optional[int] = None
    execution_quality: Optional[int] = None
    emotion_state: Optional[str] = None
    mistake_tags: Optional[list[str]] = None
    lesson_learned: Optional[str] = None


class JournalUpdateRequest(BaseModel):
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    execution_quality: Optional[int] = None
    emotion_state: Optional[str] = None
    mistake_tags: Optional[list[str]] = None
    lesson_learned: Optional[str] = None
    journal_status: Optional[str] = None


class JournalView(BaseModel):
    id: int
    account_id: str
    symbol: str
    direction: str
    entry_date: Optional[date] = None
    exit_date: Optional[date] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    quantity: Optional[float] = None
    realized_pnl: Optional[float] = None
    plan_id: Optional[int] = None
    execution_quality: Optional[int] = None
    emotion_state: Optional[str] = None
    mistake_tags: Optional[list[str]] = None
    lesson_learned: Optional[str] = None
    ai_review: Optional[str] = None
    journal_status: str = "DRAFT"
    signal_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class JournalListResponse(BaseModel):
    status: str = "ok"
    total: int = 0
    items: list[JournalView] = []
    page: int = 1
    size: int = 20


class JournalAiReviewResponse(BaseModel):
    status: str = "ok"
    journal_id: int
    ai_review: str


class JournalWeeklyReportResponse(BaseModel):
    status: str = "ok"
    week_start: date
    week_end: date
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    report: str = ""
