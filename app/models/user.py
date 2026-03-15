from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    default_role_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    permissions_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_system_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
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

    default_role = relationship(
        "Role",
        back_populates="default_for_users",
        lazy="selectin",
        foreign_keys=[default_role_id],
    )
    role_bindings = relationship(
        "UserRoleBinding",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    authz_audit_logs = relationship(
        "AuthorizationAuditLog",
        back_populates="user",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_status", "status"),
    )
