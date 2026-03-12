from unittest.mock import AsyncMock

import pytest

from app.routers.positions import list_active_positions, portfolio_summary


@pytest.mark.asyncio
async def test_list_active_positions_uses_broker_first_read_model(monkeypatch):
    monkeypatch.setattr(
        "app.routers.positions.truth_source_service.get_positions_read_model",
        AsyncMock(
            return_value={
                "items": [
                    {"symbol": "AMD", "truth_source": "BROKER_LIVE_OVERRIDE"},
                    {"symbol": "PLTR", "truth_source": "BROKER_LIVE_OVERRIDE"},
                ]
            }
        ),
    )

    result = await list_active_positions(account_id="acc-1", db=AsyncMock())

    assert [row["symbol"] for row in result] == ["AMD", "PLTR"]
    assert all(row["truth_source"] == "BROKER_LIVE_OVERRIDE" for row in result)


@pytest.mark.asyncio
async def test_portfolio_summary_exposes_mismatch_metadata(monkeypatch):
    monkeypatch.setattr(
        "app.routers.positions.truth_source_service.get_positions_read_model",
        AsyncMock(
            return_value={
                "items": [],
                "source": "BROKER_LIVE_OVERRIDE",
                "active_positions": 4,
                "broker_active_positions": 4,
                "lifecycle_active_positions": 3,
                "mismatch_detected": True,
                "mismatch_symbols": ["ORCL", "AMD"],
            }
        ),
    )

    fake_query_service = AsyncMock()
    fake_query_service.get_portfolio_summary = AsyncMock(
        return_value={
            "active_positions": 3,
            "exception_positions": 1,
            "stuck_slices": 0,
        }
    )
    monkeypatch.setattr(
        "app.routers.positions.PositionQueryService",
        lambda _db: fake_query_service,
    )

    result = await portfolio_summary(account_id="acc-1", db=AsyncMock())

    assert result["active_positions"] == 4
    assert result["active_positions_source"] == "BROKER_LIVE_OVERRIDE"
    assert result["broker_active_positions"] == 4
    assert result["lifecycle_active_positions"] == 3
    assert result["exception_positions"] == 0
    assert result["lifecycle_exception_positions"] == 1
    assert result["mismatch_detected"] is True
    assert result["mismatch_symbols"] == ["ORCL", "AMD"]
