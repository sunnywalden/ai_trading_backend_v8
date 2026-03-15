from __future__ import annotations

import logging

from app.broker.dummy_option_client import DummyOptionClient
from app.broker.option_client_base import OptionBrokerClient
from app.broker.tiger_option_client import TigerOptionClient
from app.core.config import settings
from app.core.credential_store import (
    CredentialStoreError,
    decrypt_private_key,
    materialize_private_key,
)
from app.models.broker_account import BrokerAccount
from app.models.broker_account_credential import BrokerAccountCredential
from app.models.db import SessionLocal
from app.services.broker_account_service import broker_account_service

logger = logging.getLogger(__name__)


class BrokerAccountRegistry:
    _instances: dict[str, OptionBrokerClient] = {}
    _default_instance: OptionBrokerClient | None = None

    @classmethod
    def _build_default_client(cls) -> OptionBrokerClient:
        if cls._default_instance is not None:
            return cls._default_instance
        if settings.TIGER_PRIVATE_KEY_PATH and settings.TIGER_ID:
            cls._default_instance = TigerOptionClient(
                private_key_path=settings.TIGER_PRIVATE_KEY_PATH,
                tiger_id=settings.TIGER_ID,
                account=settings.TIGER_ACCOUNT,
            )
        else:
            if not getattr(settings, "RUNTIME_ALLOW_DUMMY_BROKER", False):
                raise RuntimeError(
                    "Tiger API config missing and runtime dummy broker fallback is disabled"
                )
            cls._default_instance = DummyOptionClient()
        return cls._default_instance

    @classmethod
    def get(cls, account_id: str | None = None) -> OptionBrokerClient:
        target_account_id = str(account_id or settings.TIGER_ACCOUNT)
        if not settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED:
            return cls._build_default_client()
        if target_account_id in cls._instances:
            return cls._instances[target_account_id]
        if target_account_id == settings.TIGER_ACCOUNT:
            client = cls._build_default_client()
            cls._instances[target_account_id] = client
            return client
        raise KeyError(f"Broker account {target_account_id} is not registered")

    @classmethod
    async def register_account(
        cls,
        account: BrokerAccount,
        credential: BrokerAccountCredential,
    ) -> None:
        if not account.is_active:
            cls._instances.pop(account.account_id, None)
            return
        try:
            private_key_pem = decrypt_private_key(credential.private_key_enc)
            private_key_path = materialize_private_key(
                account.account_id,
                private_key_pem,
            )
            cls._instances[account.account_id] = TigerOptionClient(
                private_key_path=private_key_path,
                tiger_id=credential.tiger_id,
                account=account.account_id,
            )
        except CredentialStoreError as exc:
            logger.warning(
                "[BrokerAccountRegistry] skip account=%s: %s",
                account.account_id,
                exc,
            )

    @classmethod
    async def deregister(cls, account_id: str) -> None:
        cls._instances.pop(account_id, None)

    @classmethod
    async def list_active(cls) -> list[str]:
        return sorted(cls._instances.keys())

    @classmethod
    async def prewarm_from_database(cls) -> None:
        if not settings.BROKER_ACCOUNT_REGISTRY_V1131_ENABLED:
            return
        if not settings.MULTI_ACCOUNT_V1131_ENABLED:
            return
        if settings.TIGER_ACCOUNT:
            cls._instances[settings.TIGER_ACCOUNT] = cls._build_default_client()
        async with SessionLocal() as session:
            accounts = await broker_account_service.list_accounts(session)
            for item in accounts:
                if not item["credential_configured"] or not item["is_active"]:
                    continue
                account = await broker_account_service.get_account(
                    session,
                    item["id"],
                )
                if account is None or account.credentials is None:
                    continue
                await cls.register_account(account, account.credentials)
