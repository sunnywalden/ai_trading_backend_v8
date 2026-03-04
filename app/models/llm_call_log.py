"""llm_call_log.py — V10.4 M1 T1.5

LLM 调用全量日志表，用于监控成功率、P95 延迟和 token 消耗。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class LlmCallLog(Base):
    """LLM 调用日志记录。"""

    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), index=True)
    caller: Mapped[str] = mapped_column(String(64), nullable=False, comment="调用方服务名")
    model: Mapped[str] = mapped_column(String(64), nullable=False, comment="使用的模型")
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="输入 token 数")
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="输出 token 数")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="调用耗时（ms）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SUCCESS",
        comment="SUCCESS / TIMEOUT / RATE_LIMITED / ERROR"
    )
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否降级响应")
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow,
        server_default=func.now(), index=True
    )
