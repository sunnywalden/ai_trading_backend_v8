from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth_context import UserContext
from app.core.config import settings
from app.core.credential_store import encrypt_private_key, fingerprint_private_key
from app.models.broker_account import BrokerAccount
from app.models.broker_account_credential import BrokerAccountCredential
from app.models.user import User
from app.models.user_broker_account_grant import UserBrokerAccountGrant

GRANT_LEVELS = {"VIEW", "ANALYZE", "OPERATE", "ADMIN"}
BROKER_ACCOUNT_NOT_FOUND = "Broker account not found"


class BrokerAccountService:
    @staticmethod
    def _fallback_grant_for_role(role: str) -> str:
        normalized = (role or "").upper()
        if normalized == "ADMINISTRATOR":
            return "ADMIN"
        if normalized == "TRADER":
            return "OPERATE"
        if normalized in {"RESEARCHER", "SUPERVISOR"}:
            return "ANALYZE"
        return "VIEW"

    @staticmethod
    def _account_to_view(account: BrokerAccount) -> dict[str, Any]:
        credential = account.credentials
        return {
            "id": account.id,
            "account_id": account.account_id,
            "display_name": account.display_name,
            "account_type": account.account_type,
            "market": account.market,
            "tiger_id": account.tiger_id,
            "credential_ref": account.credential_ref,
            "credential_configured": credential is not None,
            "key_fingerprint": (
                credential.key_fingerprint if credential is not None else None
            ),
            "is_active": account.is_active,
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }

    @staticmethod
    def _grant_to_view(grant: UserBrokerAccountGrant) -> dict[str, Any]:
        account = grant.broker_account
        return {
            "id": grant.id,
            "user_id": grant.user_id,
            "broker_account_id": grant.broker_account_id,
            "account_id": account.account_id if account is not None else "",
            "display_name": (account.display_name if account is not None else None),
            "grant_level": grant.grant_level,
            "is_active": grant.is_active,
            "granted_at": grant.granted_at,
            "revoked_at": grant.revoked_at,
        }

    async def list_accounts(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(BrokerAccount)
            .options(selectinload(BrokerAccount.credentials))
            .order_by(
                BrokerAccount.is_active.desc(),
                BrokerAccount.account_id.asc(),
            )
        )
        accounts = list((await session.execute(stmt)).scalars().all())
        return [self._account_to_view(item) for item in accounts]

    async def get_account(
        self, session: AsyncSession, account_id: int
    ) -> BrokerAccount | None:
        stmt = (
            select(BrokerAccount)
            .options(selectinload(BrokerAccount.credentials))
            .where(BrokerAccount.id == account_id)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def create_account(
        self,
        session: AsyncSession,
        *,
        account_id: str,
        display_name: str | None,
        account_type: str,
        market: str,
        tiger_id: str | None,
    ) -> dict[str, Any]:
        existing = (
            await session.execute(
                select(BrokerAccount).where(BrokerAccount.account_id == account_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Broker account {account_id} already exists")
        account = BrokerAccount(
            account_id=account_id,
            display_name=display_name,
            account_type=account_type.upper(),
            market=market.upper(),
            tiger_id=tiger_id,
            is_active=True,
        )
        session.add(account)
        await session.commit()
        refreshed = await self.get_account(session, account.id)
        if refreshed is None:
            raise ValueError("Broker account refresh failed after create")
        return self._account_to_view(refreshed)

    async def update_account(
        self,
        session: AsyncSession,
        *,
        account_db_id: int,
        display_name: str | None = None,
        account_type: str | None = None,
        market: str | None = None,
        tiger_id: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        account = await self.get_account(session, account_db_id)
        if account is None:
            raise ValueError(BROKER_ACCOUNT_NOT_FOUND)
        if display_name is not None:
            account.display_name = display_name
        if account_type is not None:
            account.account_type = account_type.upper()
        if market is not None:
            account.market = market.upper()
        if tiger_id is not None:
            account.tiger_id = tiger_id
        if is_active is not None:
            account.is_active = is_active
        await session.commit()
        refreshed = await self.get_account(session, account.id)
        if refreshed is None:
            raise ValueError("Broker account refresh failed after update")
        return self._account_to_view(refreshed)

    async def deactivate_account(
        self,
        session: AsyncSession,
        *,
        account_db_id: int,
    ) -> dict[str, Any]:
        return await self.update_account(
            session,
            account_db_id=account_db_id,
            is_active=False,
        )

    async def upsert_credentials(
        self,
        session: AsyncSession,
        *,
        account_db_id: int,
        tiger_id: str,
        private_key_pem: str,
    ) -> dict[str, Any]:
        account = await self.get_account(session, account_db_id)
        if account is None:
            raise ValueError(BROKER_ACCOUNT_NOT_FOUND)

        encrypted = encrypt_private_key(private_key_pem)
        fingerprint = fingerprint_private_key(private_key_pem)
        credential = account.credentials
        if credential is None:
            credential = BrokerAccountCredential(
                broker_account_id=account.id,
                tiger_id=tiger_id,
                private_key_enc=encrypted,
                key_fingerprint=fingerprint,
            )
            session.add(credential)
        else:
            credential.tiger_id = tiger_id
            credential.private_key_enc = encrypted
            credential.key_fingerprint = fingerprint

        account.tiger_id = tiger_id
        account.credential_ref = f"broker_account:{account.id}"
        await session.commit()
        refreshed = await self.get_account(session, account.id)
        if refreshed is None:
            raise ValueError("Broker account refresh failed after credential update")
        return self._account_to_view(refreshed)

    async def list_user_grants(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(UserBrokerAccountGrant)
            .options(selectinload(UserBrokerAccountGrant.broker_account))
            .where(
                UserBrokerAccountGrant.user_id == user_id,
                UserBrokerAccountGrant.is_active.is_(True),
            )
            .order_by(UserBrokerAccountGrant.granted_at.desc())
        )
        grants = list((await session.execute(stmt)).scalars().all())
        return [self._grant_to_view(item) for item in grants]

    async def upsert_user_grant(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        broker_account_id: int,
        grant_level: str,
        granted_by: int | None,
    ) -> dict[str, Any]:
        normalized_level = grant_level.upper()
        if normalized_level not in GRANT_LEVELS:
            raise ValueError("Invalid grant level")
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")
        account = await self.get_account(session, broker_account_id)
        if account is None:
            raise ValueError(BROKER_ACCOUNT_NOT_FOUND)

        existing = (
            await session.execute(
                select(UserBrokerAccountGrant)
                .options(selectinload(UserBrokerAccountGrant.broker_account))
                .where(
                    UserBrokerAccountGrant.user_id == user_id,
                    (UserBrokerAccountGrant.broker_account_id == broker_account_id),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = UserBrokerAccountGrant(
                user_id=user_id,
                broker_account_id=broker_account_id,
                grant_level=normalized_level,
                granted_by=granted_by,
                is_active=True,
            )
            session.add(existing)
        else:
            existing.grant_level = normalized_level
            existing.granted_by = granted_by
            existing.revoked_at = None
            existing.is_active = True

        user.permissions_version += 1
        await session.commit()
        refreshed = (
            await session.execute(
                select(UserBrokerAccountGrant)
                .options(selectinload(UserBrokerAccountGrant.broker_account))
                .where(UserBrokerAccountGrant.id == existing.id)
            )
        ).scalar_one()
        return self._grant_to_view(refreshed)

    async def revoke_user_grant(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        grant_id: int,
    ) -> dict[str, Any]:
        grant = (
            await session.execute(
                select(UserBrokerAccountGrant)
                .options(selectinload(UserBrokerAccountGrant.broker_account))
                .where(
                    UserBrokerAccountGrant.id == grant_id,
                    UserBrokerAccountGrant.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            raise ValueError("Account grant not found")
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        grant.is_active = False
        grant.revoked_at = grant.revoked_at or datetime.now(UTC).replace(tzinfo=None)
        user.permissions_version += 1
        await session.commit()
        return self._grant_to_view(grant)

    async def list_accessible_accounts_for_context(
        self,
        session: AsyncSession,
        user_ctx: UserContext,
    ) -> list[dict[str, Any]]:
        fallback_id = (
            user_ctx.default_account_id or settings.TIGER_ACCOUNT or "demo-account"
        )
        accessible_ids = [
            account_id
            for account_id in dict.fromkeys(user_ctx.accessible_account_ids)
            if account_id
        ]
        if not settings.MULTI_ACCOUNT_V1131_ENABLED:
            accessible_ids = [fallback_id]

        if not accessible_ids:
            return [
                {
                    "id": None,
                    "account_id": fallback_id,
                    "display_name": "Default Tiger Account",
                    "account_type": "LIVE",
                    "market": "US",
                    "grant_level": self._fallback_grant_for_role(user_ctx.role),
                    "is_active": True,
                }
            ]

        stmt = (
            select(BrokerAccount)
            .where(BrokerAccount.account_id.in_(accessible_ids))
            .order_by(BrokerAccount.account_id.asc())
        )
        accounts = list((await session.execute(stmt)).scalars().all())
        account_map = {item.account_id: item for item in accounts}
        items: list[dict[str, Any]] = []
        for account_id in accessible_ids:
            account = account_map.get(account_id)
            grant_level = user_ctx.account_grants.get(
                account_id,
                self._fallback_grant_for_role(user_ctx.role),
            )
            if account is None:
                items.append(
                    {
                        "id": None,
                        "account_id": account_id,
                        "display_name": account_id,
                        "account_type": "LIVE",
                        "market": "US",
                        "grant_level": grant_level,
                        "is_active": True,
                    }
                )
                continue
            items.append(
                {
                    "id": account.id,
                    "account_id": account.account_id,
                    "display_name": account.display_name,
                    "account_type": account.account_type,
                    "market": account.market,
                    "grant_level": grant_level,
                    "is_active": account.is_active,
                }
            )
        return items


broker_account_service = BrokerAccountService()
