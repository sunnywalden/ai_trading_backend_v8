from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    account_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="LIVE",
        server_default="LIVE",
    )
    market: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="US",
        server_default="US",
    )
    tiger_id: Mapped[Optional[str]] = mapped_column(String(64))
    credential_ref: Mapped[Optional[str]] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    credentials = relationship(
        "BrokerAccountCredential",
        back_populates="broker_account",
        lazy="selectin",
        cascade="all, delete-orphan",
        uselist=False,
    )
    user_grants = relationship(
        "UserBrokerAccountGrant",
        back_populates="broker_account",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_broker_accounts_account_id", "account_id"),
        Index("ix_broker_accounts_is_active", "is_active"),
    )
