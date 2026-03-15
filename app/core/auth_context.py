from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings

ACCESS_MODE_RANK = {
    "summary": 0,
    "readonly": 1,
    "standard": 2,
    "write": 2,
}

ACCOUNT_GRANT_RANK = {
    "VIEW": 0,
    "ANALYZE": 1,
    "OPERATE": 2,
    "ADMIN": 3,
}


@dataclass(slots=True)
class UserContext:
    username: str
    role: str = "ADMINISTRATOR"
    display_name: str | None = None
    user_id: int | None = None
    permissions: set[str] = field(default_factory=set)
    permissions_version: int = 1
    status: str = "ACTIVE"
    is_system_seed: bool = False
    must_change_password: bool = False
    legacy_mode: bool = False
    accessible_account_ids: list[str] = field(default_factory=list)
    default_account_id: str | None = None
    account_grants: dict[str, str] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return self.role == role

    def has_any_role(self, roles: set[str]) -> bool:
        return self.role in roles or "*" in roles

    def has_permission(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def has_access_mode(self, required_mode: str) -> bool:
        current_mode = (
            "standard"
            if self.role in {"ADMINISTRATOR", "TRADER", "RESEARCHER"}
            else "summary"
        )
        return ACCESS_MODE_RANK.get(current_mode, 0) >= ACCESS_MODE_RANK.get(
            required_mode, 0
        )

    def has_account_access(
        self,
        account_id: str,
        min_level: str = "VIEW",
    ) -> bool:
        if not account_id:
            return False
        grant_level = self.account_grants.get(account_id)
        if grant_level is None and account_id == self.default_account_id:
            grant_level = _default_account_grant_for_role(self.role)
        return ACCOUNT_GRANT_RANK.get(
            (grant_level or "").upper(),
            -1,
        ) >= ACCOUNT_GRANT_RANK.get(
            min_level.upper(),
            0,
        )


FULL_ACCESS = {"*"}


def _default_account_grant_for_role(role: str) -> str:
    normalized = (role or "").upper()
    if normalized == "ADMINISTRATOR":
        return "ADMIN"
    if normalized == "TRADER":
        return "OPERATE"
    if normalized in {"RESEARCHER", "SUPERVISOR"}:
        return "ANALYZE"
    return "VIEW"


def make_legacy_admin_context(username: str) -> UserContext:
    default_account_id = settings.TIGER_ACCOUNT or "demo-account"
    return UserContext(
        username=username,
        role="ADMINISTRATOR",
        display_name=username,
        permissions=FULL_ACCESS.copy(),
        permissions_version=1,
        status="ACTIVE",
        is_system_seed=False,
        must_change_password=False,
        legacy_mode=True,
        accessible_account_ids=[default_account_id],
        default_account_id=default_account_id,
        account_grants={default_account_id: "ADMIN"},
    )
