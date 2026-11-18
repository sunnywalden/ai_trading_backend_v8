"""Offline check that position display can use a local broker double."""

import pytest

from app.broker.factory import make_option_broker_client
from app.core.config import settings


@pytest.mark.asyncio
async def test_hk_stock_names(monkeypatch):
    import app.broker.factory as factory

    monkeypatch.setattr(settings, "RUNTIME_ALLOW_DUMMY_BROKER", True)
    monkeypatch.setattr(settings, "TIGER_PRIVATE_KEY_PATH", None)
    monkeypatch.setattr(settings, "TIGER_ID", None)
    factory._broker_instance = None
    try:
        client = make_option_broker_client()
        account_id = await client.get_account_id()
        positions = await client.list_underlying_positions(account_id)
    finally:
        factory._broker_instance = None

    assert account_id
    assert positions
    for pos in positions:
        assert pos.symbol
        assert pos.last_price > 0
        assert (pos.name or pos.symbol)
