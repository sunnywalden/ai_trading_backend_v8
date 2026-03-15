from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_system_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
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

    permission_grants = relationship(
        "RolePermissionGrant",
        back_populates="role",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    user_bindings = relationship(
        "UserRoleBinding",
        back_populates="role",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    default_for_users = relationship(
        "User",
        back_populates="default_role",
        lazy="selectin",
        foreign_keys="User.default_role_id",
    )

    __table_args__ = (Index("ix_roles_code", "code"),)
