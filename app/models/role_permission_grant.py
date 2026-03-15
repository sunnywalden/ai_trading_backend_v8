from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class RolePermissionGrant(Base):
    __tablename__ = "role_permission_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    grant_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="global"
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

    role = relationship("Role", back_populates="permission_grants", lazy="selectin")
    permission = relationship(
        "Permission", back_populates="role_grants", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission_grant"),
        Index("ix_role_permission_role", "role_id"),
    )
