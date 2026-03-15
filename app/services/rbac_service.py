from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth_context import UserContext
from app.core.config import settings
from app.models.authorization_audit_log import AuthorizationAuditLog
from app.models.broker_account import BrokerAccount
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission_grant import RolePermissionGrant
from app.models.user import User
from app.models.user_broker_account_grant import UserBrokerAccountGrant
from app.models.user_role_binding import UserRoleBinding

ROLE_RESEARCHER = "RESEARCHER"
ROLE_TRADER = "TRADER"
ROLE_SUPERVISOR = "SUPERVISOR"
ROLE_ADMINISTRATOR = "ADMINISTRATOR"

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ROUNDS = 120_000

BUILTIN_ROLES: dict[str, dict[str, Any]] = {
    ROLE_RESEARCHER: {
        "name": "Researcher",
        "description": "研究员工作台与研究配置权限",
    },
    ROLE_TRADER: {
        "name": "Trader",
        "description": "交易员执行、持仓与归因权限",
    },
    ROLE_SUPERVISOR: {
        "name": "Supervisor",
        "description": "主管报表与经营摘要权限",
    },
    ROLE_ADMINISTRATOR: {
        "name": "Administrator",
        "description": "管理员治理、用户与系统权限",
    },
}

BUILTIN_PERMISSIONS: list[dict[str, str]] = [
    {
        "code": "research.home.read",
        "resource": "research",
        "action": "home.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问研究员首页",
    },
    {
        "code": "research.alpha_lab.read",
        "resource": "research",
        "action": "alpha_lab.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问 Alpha Lab",
    },
    {
        "code": "research.opportunities.read",
        "resource": "research",
        "action": "opportunities.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问机会扫描",
    },
    {
        "code": "research.strategy.read",
        "resource": "research",
        "action": "strategy.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看策略",
    },
    {
        "code": "research.strategy.manage",
        "resource": "research",
        "action": "strategy.manage",
        "scope": "global",
        "access_mode": "write",
        "description": "管理策略",
    },
    {
        "code": "research.strategy.execute",
        "resource": "research",
        "action": "strategy.execute",
        "scope": "global",
        "access_mode": "write",
        "description": "触发策略扫描执行",
    },
    {
        "code": "research.backtest.read",
        "resource": "research",
        "action": "backtest.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看回测",
    },
    {
        "code": "research.export.read",
        "resource": "research",
        "action": "export.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "导出研究结果",
    },
    {
        "code": "trading.home.read",
        "resource": "trading",
        "action": "home.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问交易员首页",
    },
    {
        "code": "trading.order_book.read",
        "resource": "trading",
        "action": "order_book.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问订单簿",
    },
    {
        "code": "trading.execution_policy.read",
        "resource": "trading",
        "action": "execution_policy.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看执行策略",
    },
    {
        "code": "trading.execution_policy.manage",
        "resource": "trading",
        "action": "execution_policy.manage",
        "scope": "global",
        "access_mode": "write",
        "description": "修改执行策略",
    },
    {
        "code": "trading.trade.execute",
        "resource": "trading",
        "action": "trade.execute",
        "scope": "global",
        "access_mode": "write",
        "description": "执行交易动作",
    },
    {
        "code": "trading.positions.read",
        "resource": "trading",
        "action": "positions.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看持仓",
    },
    {
        "code": "trading.position_evaluation.read",
        "resource": "trading",
        "action": "position_evaluation.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看持仓评估",
    },
    {
        "code": "trading.paper.read",
        "resource": "trading",
        "action": "paper.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看模拟盘",
    },
    {
        "code": "trading.journal.read",
        "resource": "trading",
        "action": "journal.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看交易日志",
    },
    {
        "code": "trading.attribution.read",
        "resource": "trading",
        "action": "attribution.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看交易归因",
    },
    {
        "code": "trading.alerts.read",
        "resource": "trading",
        "action": "alerts.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看告警中心",
    },
    {
        "code": "executive.home.read",
        "resource": "executive",
        "action": "home.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "访问主管首页",
    },
    {
        "code": "executive.report.executive.read",
        "resource": "executive",
        "action": "report.executive.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "访问主管经营报表",
    },
    {
        "code": "executive.report.risk.read",
        "resource": "executive",
        "action": "report.risk.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "访问主管风险报表",
    },
    {
        "code": "executive.report.performance.read",
        "resource": "executive",
        "action": "report.performance.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "访问主管绩效报表",
    },
    {
        "code": "executive.autonomy.read",
        "resource": "executive",
        "action": "autonomy.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "查看自主中枢摘要",
    },
    {
        "code": "admin.home.read",
        "resource": "admin",
        "action": "home.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "访问管理员首页",
    },
    {
        "code": "admin.user.manage",
        "resource": "admin",
        "action": "user.manage",
        "scope": "global",
        "access_mode": "write",
        "description": "管理用户",
    },
    {
        "code": "admin.role.manage",
        "resource": "admin",
        "action": "role.manage",
        "scope": "global",
        "access_mode": "write",
        "description": "管理角色",
    },
    {
        "code": "admin.permission.read",
        "resource": "admin",
        "action": "permission.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看权限目录",
    },
    {
        "code": "admin.audit.read",
        "resource": "admin",
        "action": "audit.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看授权审计",
    },
    {
        "code": "admin.task.operate",
        "resource": "admin",
        "action": "task.operate",
        "scope": "global",
        "access_mode": "write",
        "description": "操作调度任务",
    },
    {
        "code": "admin.system.read",
        "resource": "admin",
        "action": "system.read",
        "scope": "global",
        "access_mode": "standard",
        "description": "查看系统监控",
    },
    {
        "code": "admin.broker_account.manage",
        "resource": "admin",
        "action": "broker_account.manage",
        "scope": "global",
        "access_mode": "write",
        "description": "管理经纪账户与账户授权",
    },
    {
        "code": "common.dashboard.read",
        "resource": "common",
        "action": "dashboard.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "查看共享 Dashboard",
    },
    {
        "code": "common.autonomy.read",
        "resource": "common",
        "action": "autonomy.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "查看自主中枢摘要",
    },
    {
        "code": "common.copilot.read",
        "resource": "common",
        "action": "copilot.read",
        "scope": "global",
        "access_mode": "summary",
        "description": "查看 Copilot 页面",
    },
]

ROLE_PERMISSION_CODES: dict[str, set[str]] = {
    ROLE_RESEARCHER: {
        "research.home.read",
        "research.alpha_lab.read",
        "research.opportunities.read",
        "research.strategy.read",
        "research.strategy.manage",
        "research.backtest.read",
        "research.export.read",
        "common.dashboard.read",
        "common.autonomy.read",
        "common.copilot.read",
    },
    ROLE_TRADER: {
        "trading.home.read",
        "trading.order_book.read",
        "trading.execution_policy.read",
        "trading.execution_policy.manage",
        "trading.trade.execute",
        "trading.positions.read",
        "trading.position_evaluation.read",
        "trading.paper.read",
        "trading.journal.read",
        "trading.attribution.read",
        "trading.alerts.read",
        "research.strategy.read",
        "research.strategy.execute",
        "common.dashboard.read",
        "common.autonomy.read",
        "common.copilot.read",
    },
    ROLE_SUPERVISOR: {
        "executive.home.read",
        "executive.report.executive.read",
        "executive.report.risk.read",
        "executive.report.performance.read",
        "executive.autonomy.read",
        "trading.attribution.read",
        "common.dashboard.read",
        "common.autonomy.read",
        "common.copilot.read",
    },
    ROLE_ADMINISTRATOR: {item["code"] for item in BUILTIN_PERMISSIONS},
}

SEED_ENV_VARS = {
    ROLE_RESEARCHER: "SEED_RESEARCHER_PASSWORD",
    ROLE_TRADER: "SEED_TRADER_PASSWORD",
    ROLE_SUPERVISOR: "SEED_SUPERVISOR_PASSWORD",
    ROLE_ADMINISTRATOR: "SEED_ADMIN_PASSWORD",
}

SEED_USERNAMES = {
    ROLE_RESEARCHER: "researcher",
    ROLE_TRADER: "trader",
    ROLE_SUPERVISOR: "supervisor",
    ROLE_ADMINISTRATOR: "admin",
}

SEED_DISPLAY_NAMES = {
    ROLE_RESEARCHER: "Researcher Seed",
    ROLE_TRADER: "Trader Seed",
    ROLE_SUPERVISOR: "Supervisor Seed",
    ROLE_ADMINISTRATOR: "Administrator Seed",
}


class RbacService:
    def hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            PBKDF2_ROUNDS,
        )
        return "pbkdf2_sha256${rounds}${salt}${digest}".format(
            rounds=PBKDF2_ROUNDS,
            salt=base64.urlsafe_b64encode(salt).decode("ascii"),
            digest=base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            scheme, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            rounds_int = int(rounds)
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        except Exception:
            return False
        candidate = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            rounds_int,
        )
        return hmac.compare_digest(candidate, expected)

    async def ensure_builtin_rbac(self, session: AsyncSession) -> None:
        roles = {
            role.code: role
            for role in (await session.execute(select(Role))).scalars().all()
        }
        for code, payload in BUILTIN_ROLES.items():
            role = roles.get(code)
            if role is None:
                role = Role(
                    code=code,
                    name=payload["name"],
                    description=payload["description"],
                    is_system_builtin=True,
                )
                session.add(role)
                await session.flush()
                roles[code] = role
            else:
                role.name = payload["name"]
                role.description = payload["description"]
                role.is_system_builtin = True

        permissions = {
            permission.code: permission
            for permission in (await session.execute(select(Permission)))
            .scalars()
            .all()
        }
        for payload in BUILTIN_PERMISSIONS:
            permission = permissions.get(payload["code"])
            if permission is None:
                permission = Permission(**payload)
                session.add(permission)
                await session.flush()
                permissions[payload["code"]] = permission
            else:
                permission.resource = payload["resource"]
                permission.action = payload["action"]
                permission.scope = payload["scope"]
                permission.access_mode = payload["access_mode"]
                permission.description = payload["description"]

        existing_grants = {
            (grant.role_id, grant.permission_id)
            for grant in (await session.execute(select(RolePermissionGrant)))
            .scalars()
            .all()
        }
        for role_code, permission_codes in ROLE_PERMISSION_CODES.items():
            role = roles[role_code]
            for permission_code in permission_codes:
                permission = permissions[permission_code]
                key = (role.id, permission.id)
                if key in existing_grants:
                    continue
                session.add(
                    RolePermissionGrant(
                        role_id=role.id,
                        permission_id=permission.id,
                        grant_scope="global",
                    )
                )
                existing_grants.add(key)
        await session.commit()

    async def create_seed_users(
        self, session: AsyncSession, password_map: dict[str, str]
    ) -> None:
        await self.ensure_builtin_rbac(session)
        roles = {
            role.code: role
            for role in (await session.execute(select(Role))).scalars().all()
        }
        existing_users = {
            user.username: user
            for user in (await session.execute(select(User))).scalars().all()
        }
        for role_code, username in SEED_USERNAMES.items():
            password = (password_map.get(role_code) or "").strip()
            if not password:
                continue
            user = existing_users.get(username)
            role = roles[role_code]
            if user is None:
                user = User(
                    username=username,
                    display_name=SEED_DISPLAY_NAMES[role_code],
                    password_hash=self.hash_password(password),
                    status="ACTIVE",
                    default_role_id=role.id,
                    permissions_version=1,
                    is_system_seed=True,
                    must_change_password=True,
                )
                session.add(user)
                await session.flush()
                existing_users[username] = user
            else:
                user.display_name = user.display_name or SEED_DISPLAY_NAMES[role_code]
                user.default_role_id = role.id
                user.is_system_seed = True
                if not user.password_hash:
                    user.password_hash = self.hash_password(password)
                    user.must_change_password = True
            binding = (
                await session.execute(
                    select(UserRoleBinding).where(
                        UserRoleBinding.user_id == user.id,
                        UserRoleBinding.role_id == role.id,
                    )
                )
            ).scalar_one_or_none()
            if binding is None:
                session.add(
                    UserRoleBinding(
                        user_id=user.id,
                        role_id=role.id,
                        is_active=True,
                        assigned_by="bootstrap",
                    )
                )
        await session.commit()

    async def get_user_with_roles(
        self,
        session: AsyncSession,
        *,
        username: str | None = None,
        user_id: int | None = None,
    ) -> User | None:
        stmt = (
            select(User)
            .options(
                selectinload(User.default_role),
                selectinload(User.role_bindings)
                .selectinload(UserRoleBinding.role)
                .selectinload(Role.permission_grants)
                .selectinload(RolePermissionGrant.permission),
                selectinload(User.account_grants).selectinload(
                    UserBrokerAccountGrant.broker_account
                ),
            )
            .execution_options(populate_existing=True)
        )
        if username is not None:
            stmt = stmt.where(User.username == username)
        if user_id is not None:
            stmt = stmt.where(User.id == user_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    def build_user_context(self, user: User) -> UserContext:
        active_roles = [
            binding.role
            for binding in user.role_bindings
            if binding.is_active and binding.role is not None
        ]
        primary_role = active_roles[0] if active_roles else user.default_role
        role_code = (
            primary_role.code if primary_role is not None else ROLE_ADMINISTRATOR
        )
        permissions: set[str] = set()
        for role in active_roles or (
            [primary_role] if primary_role is not None else []
        ):
            if role is None:
                continue
            for grant in role.permission_grants:
                if grant.permission is not None:
                    permissions.add(grant.permission.code)
        if role_code == ROLE_ADMINISTRATOR:
            permissions.add("*")
        active_grants = [
            grant
            for grant in user.account_grants
            if grant.is_active
            and grant.revoked_at is None
            and grant.broker_account is not None
            and grant.broker_account.is_active
        ]
        account_grants = {
            grant.broker_account.account_id: grant.grant_level.upper()
            for grant in active_grants
        }
        accessible_account_ids = [
            account_id for account_id in account_grants.keys() if account_id
        ]
        if not accessible_account_ids:
            fallback_account_id = settings.TIGER_ACCOUNT or "demo-account"
            fallback_level = (
                "ADMIN"
                if role_code == ROLE_ADMINISTRATOR
                else "OPERATE" if role_code == ROLE_TRADER else "ANALYZE"
            )
            accessible_account_ids = [fallback_account_id]
            account_grants = {fallback_account_id: fallback_level}
        default_account_id = settings.TIGER_ACCOUNT or accessible_account_ids[0]
        if default_account_id not in account_grants:
            default_account_id = accessible_account_ids[0]
        return UserContext(
            username=user.username,
            role=role_code,
            display_name=user.display_name,
            user_id=user.id,
            permissions=permissions,
            permissions_version=user.permissions_version,
            status=user.status,
            is_system_seed=user.is_system_seed,
            must_change_password=user.must_change_password,
            legacy_mode=False,
            accessible_account_ids=accessible_account_ids,
            default_account_id=default_account_id,
            account_grants=account_grants,
        )

    async def authenticate_user(
        self,
        session: AsyncSession,
        username: str,
        password: str,
    ) -> UserContext | None:
        user = await self.get_user_with_roles(session, username=username)
        if user is None or user.status != "ACTIVE":
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        await session.refresh(user)
        refreshed_user = await self.get_user_with_roles(session, user_id=user.id)
        if refreshed_user is None:
            return None
        return self.build_user_context(refreshed_user)

    async def get_user_context_by_username(
        self,
        session: AsyncSession,
        username: str,
    ) -> UserContext | None:
        user = await self.get_user_with_roles(session, username=username)
        if user is None or user.status != "ACTIVE":
            return None
        return self.build_user_context(user)

    async def list_users(self, session: AsyncSession) -> list[dict[str, Any]]:
        users = list(
            (await session.execute(select(User).order_by(User.username.asc())))
            .scalars()
            .all()
        )
        result: list[dict[str, Any]] = []
        for user in users:
            full = await self.get_user_with_roles(session, user_id=user.id)
            if full is None:
                continue
            ctx = self.build_user_context(full)
            result.append(
                {
                    "id": full.id,
                    "username": full.username,
                    "display_name": full.display_name,
                    "status": full.status,
                    "default_role": ctx.role,
                    "permissions_version": full.permissions_version,
                    "is_system_seed": full.is_system_seed,
                    "must_change_password": full.must_change_password,
                    "last_login_at": full.last_login_at,
                    "created_at": full.created_at,
                }
            )
        return result

    async def list_roles(self, session: AsyncSession) -> list[dict[str, Any]]:
        roles = list(
            (await session.execute(select(Role).order_by(Role.id.asc())))
            .scalars()
            .all()
        )
        result: list[dict[str, Any]] = []
        for role in roles:
            refreshed = (
                await session.execute(
                    select(Role)
                    .options(
                        selectinload(Role.permission_grants).selectinload(
                            RolePermissionGrant.permission
                        )
                    )
                    .where(Role.id == role.id)
                )
            ).scalar_one()
            permissions = sorted(
                grant.permission.code
                for grant in refreshed.permission_grants
                if grant.permission is not None
            )
            result.append(
                {
                    "id": refreshed.id,
                    "code": refreshed.code,
                    "name": refreshed.name,
                    "description": refreshed.description,
                    "is_system_builtin": refreshed.is_system_builtin,
                    "permissions": permissions,
                    "created_at": refreshed.created_at,
                    "updated_at": refreshed.updated_at,
                }
            )
        return result

    async def list_permissions(self, session: AsyncSession) -> list[dict[str, Any]]:
        permissions = list(
            (await session.execute(select(Permission).order_by(Permission.code.asc())))
            .scalars()
            .all()
        )
        return [
            {
                "id": item.id,
                "code": item.code,
                "resource": item.resource,
                "action": item.action,
                "scope": item.scope,
                "access_mode": item.access_mode,
                "description": item.description,
            }
            for item in permissions
        ]

    async def create_user(
        self,
        session: AsyncSession,
        *,
        username: str,
        display_name: str,
        password: str,
        role_code: str,
        assigned_by: str,
    ) -> dict[str, Any]:
        await self.ensure_builtin_rbac(session)
        existing = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"User {username} already exists")
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role {role_code} not found")
        user = User(
            username=username,
            display_name=display_name,
            password_hash=self.hash_password(password),
            status="ACTIVE",
            default_role_id=role.id,
            permissions_version=1,
            is_system_seed=False,
            must_change_password=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRoleBinding(
                user_id=user.id,
                role_id=role.id,
                is_active=True,
                assigned_by=assigned_by,
            )
        )
        await session.commit()
        fresh = await self.get_user_with_roles(session, user_id=user.id)
        if fresh is None:
            raise ValueError("Failed to reload created user")
        ctx = self.build_user_context(fresh)
        return {
            "id": fresh.id,
            "username": fresh.username,
            "display_name": fresh.display_name,
            "status": fresh.status,
            "default_role": ctx.role,
            "permissions_version": fresh.permissions_version,
            "is_system_seed": fresh.is_system_seed,
            "must_change_password": fresh.must_change_password,
            "last_login_at": fresh.last_login_at,
            "created_at": fresh.created_at,
        }

    async def update_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        display_name: str | None = None,
        password: str | None = None,
        status: str | None = None,
        role_code: str | None = None,
        assigned_by: str | None = None,
    ) -> dict[str, Any]:
        user = await self.get_user_with_roles(session, user_id=user_id)
        if user is None:
            raise ValueError("User not found")
        if display_name is not None:
            user.display_name = display_name
        if password:
            user.password_hash = self.hash_password(password)
            user.must_change_password = True
            user.permissions_version += 1
        if status is not None:
            user.status = status
            user.permissions_version += 1
        if role_code:
            await self.assign_role(
                session,
                user_id=user_id,
                role_code=role_code,
                assigned_by=assigned_by or "admin",
                commit=False,
            )
            refreshed_role = (
                await session.execute(select(Role).where(Role.code == role_code))
            ).scalar_one_or_none()
            if refreshed_role is not None:
                user.default_role_id = refreshed_role.id
                user.permissions_version += 1
        await session.commit()
        fresh = await self.get_user_with_roles(session, user_id=user_id)
        if fresh is None:
            raise ValueError("Failed to reload user")
        ctx = self.build_user_context(fresh)
        return {
            "id": fresh.id,
            "username": fresh.username,
            "display_name": fresh.display_name,
            "status": fresh.status,
            "default_role": ctx.role,
            "permissions_version": fresh.permissions_version,
            "is_system_seed": fresh.is_system_seed,
            "must_change_password": fresh.must_change_password,
            "last_login_at": fresh.last_login_at,
            "created_at": fresh.created_at,
        }

    async def change_password(
        self,
        session: AsyncSession,
        *,
        username: str,
        current_password: str,
        new_password: str,
    ) -> UserContext:
        user = await self.get_user_with_roles(session, username=username)
        if user is None or user.status != "ACTIVE":
            raise ValueError("User not found or inactive")
        if not self.verify_password(current_password, user.password_hash):
            raise ValueError("Current password is incorrect")
        if current_password == new_password:
            raise ValueError("New password must be different from current password")

        user.password_hash = self.hash_password(new_password)
        user.must_change_password = False
        user.permissions_version += 1
        await session.commit()

        fresh = await self.get_user_with_roles(session, user_id=user.id)
        if fresh is None:
            raise ValueError("Failed to reload updated user")
        return self.build_user_context(fresh)

    async def assign_role(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        role_code: str,
        assigned_by: str,
        commit: bool = True,
    ) -> None:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if role is None:
            raise ValueError(f"Role {role_code} not found")
        bindings = list(
            (
                await session.execute(
                    select(UserRoleBinding).where(UserRoleBinding.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        selected_binding = None
        for binding in bindings:
            binding.is_active = binding.role_id == role.id
            if binding.role_id == role.id:
                selected_binding = binding
        if selected_binding is None:
            session.add(
                UserRoleBinding(
                    user_id=user_id,
                    role_id=role.id,
                    is_active=True,
                    assigned_by=assigned_by,
                )
            )
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is not None:
            user.default_role_id = role.id
            user.permissions_version += 1
        if commit:
            await session.commit()

    async def upsert_role(
        self,
        session: AsyncSession,
        *,
        role_id: int | None,
        code: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        role = None
        if role_id is not None:
            role = (
                await session.execute(select(Role).where(Role.id == role_id))
            ).scalar_one_or_none()
        if role is None:
            role = (
                await session.execute(select(Role).where(Role.code == code))
            ).scalar_one_or_none()
        if role is None:
            role = Role(
                code=code,
                name=name,
                description=description,
                is_system_builtin=False,
            )
            session.add(role)
        else:
            role.code = code
            role.name = name
            role.description = description
        await session.commit()
        return {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "is_system_builtin": role.is_system_builtin,
        }

    async def list_audit_logs(
        self, session: AsyncSession, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = list(
            (
                await session.execute(
                    select(AuthorizationAuditLog)
                    .order_by(AuthorizationAuditLog.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "username": row.username,
                "event_type": row.event_type,
                "resource": row.resource,
                "action": row.action,
                "decision": row.decision,
                "reason": row.reason,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "metadata": row.metadata_json or {},
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def log_authorization_event(
        self,
        session: AsyncSession,
        current_user: UserContext,
        *,
        event_type: str,
        resource: str,
        action: str,
        decision: str,
        reason: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AuthorizationAuditLog(
                user_id=current_user.user_id,
                username=current_user.username,
                event_type=event_type,
                resource=resource,
                action=action,
                decision=decision,
                reason=reason,
                target_type=target_type,
                target_id=target_id,
                metadata_json=metadata or {},
            )
        )
        await session.commit()

    def seed_password_map_from_env(self) -> dict[str, str]:
        return {
            role_code: os.getenv(env_name, "")
            for role_code, env_name in SEED_ENV_VARS.items()
        }


rbac_service = RbacService()
