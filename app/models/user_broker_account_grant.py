from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class UserBrokerAccountGrant(Base):
    __tablename__ = "user_broker_account_grants"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    broker_account_id: Mapped[int] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    grant_level: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )

    user = relationship(
        "User",
        back_populates="account_grants",
        lazy="selectin",
        foreign_keys=[user_id],
    )
    broker_account = relationship(
        "BrokerAccount",
        back_populates="user_grants",
        lazy="selectin",
    )
    granted_by_user = relationship(
        "User",
        lazy="selectin",
        foreign_keys=[granted_by],
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "broker_account_id",
            name="uq_user_broker_account_grant",
        ),
        Index(
            "ix_user_broker_account_grants_user_active",
            "user_id",
            "is_active",
        ),
        Index(
            "ix_user_broker_account_grants_account_active",
            "broker_account_id",
            "is_active",
        ),
    )
