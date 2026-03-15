from __future__ import annotations

from dataclasses import dataclass, field

ACCESS_MODE_RANK = {
    "summary": 0,
    "readonly": 1,
    "standard": 2,
    "write": 2,
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


FULL_ACCESS = {"*"}


def make_legacy_admin_context(username: str) -> UserContext:
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
    )
