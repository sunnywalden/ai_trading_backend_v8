"""Offline price and equity guards for quick trade."""

import pytest

from app.services.quick_trade_service import QuickTradeService


class _FakeMarketData:
    async def get_current_price(self, symbol: str) -> float:
        if symbol == "INVALID_SYMBOL":
            return 0.0
        return {"META": 512.25, "AAPL": 189.4}[symbol]


class _FakeBroker:
    async def get_account_equity(self, account_id: str) -> float:
        assert account_id
        return 250000.0


@pytest.mark.asyncio
async def test_price_accuracy():
    service = QuickTradeService.__new__(QuickTradeService)
    service.market_data = _FakeMarketData()
    service.broker = _FakeBroker()

    meta = await service._get_current_price("META")
    aapl = await service._get_current_price("AAPL")
    assert meta == pytest.approx(512.25)
    assert aapl == pytest.approx(189.4)
    assert meta != pytest.approx(100.0)

    with pytest.raises(ValueError):
        await service._get_current_price("INVALID_SYMBOL")

    equity = await service._get_account_equity()
    assert equity == pytest.approx(250000.0)
    assert equity != pytest.approx(1_000_000.0)
