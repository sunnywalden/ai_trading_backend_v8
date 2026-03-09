import pytest

from app.services.copilot_service import CopilotService


@pytest.mark.asyncio
async def test_morning_brief_cache_self_heals_stale_positions(monkeypatch):
    service = CopilotService()

    stale_cached = {
        "date": "2026-03-09",
        "market_regime": "MEAN_REVERT",
        "summary": "账户当前空仓，无历史盈亏记录。",
        "market_outlook": "test",
        "portfolio_snapshot": {
            "positions_count": 0,
            "unrealized_pnl_pct": None,
            "top_contributor": None,
            "beta_exposure": None,
            "mom_exposure": None,
        },
        "key_themes": [],
        "top_signals": [
            {
                "symbol": "GDRX",
                "action": "BUY",
                "reason": "test",
                "confidence": 0.98,
            }
        ],
        "risk_alerts": [],
    }

    repaired = {
        **stale_cached,
        "summary": "账户当前持有 6 个标的，主要仓位包括 AMD、MSFT、QCOM；未实现盈亏约 1.2%。",
        "portfolio_snapshot": {
            "positions_count": 6,
            "unrealized_pnl_pct": 1.2,
            "top_contributor": "AMD",
            "beta_exposure": 1.0,
            "mom_exposure": 0.2,
        },
    }

    cache_writes = []

    async def fake_resolve(_account_id: str) -> str:
        return "21272246230273657"

    async def fake_cache_get(_key: str):
        return stale_cached

    async def fake_cache_set(key: str, value, expire: int):
        cache_writes.append((key, value, expire))

    async def fake_build_context(_account_id: str):
        return {
            "positions_count": 6,
            "positions_preview": [
                {"symbol": "AMD"},
                {"symbol": "MSFT"},
                {"symbol": "QCOM"},
            ],
            "pnl_ticker": {
                "unrealized_pnl_pct": 1.2,
                "top_contributor": "AMD",
            },
            "factor_exposure": {
                "portfolio_beta": 1.0,
                "beta_mom": 0.2,
            },
            "top_signals": stale_cached["top_signals"],
        }

    def fake_normalize(result, _context):
        assert result["portfolio_snapshot"]["positions_count"] == 0
        return repaired

    monkeypatch.setattr(service, "_resolve_context_account_id", fake_resolve)
    monkeypatch.setattr(service, "_build_context", fake_build_context)
    monkeypatch.setattr(service, "_normalize_morning_brief_result", fake_normalize)

    from app.services import copilot_service as copilot_module

    monkeypatch.setattr(copilot_module.cache, "get", fake_cache_get)
    monkeypatch.setattr(copilot_module.cache, "set", fake_cache_set)

    result = await service.morning_brief("admin", force_refresh=False)

    assert result["portfolio_snapshot"]["positions_count"] == 6
    assert cache_writes
    assert cache_writes[0][1]["portfolio_snapshot"]["positions_count"] == 6


def test_morning_brief_cache_looks_stale_when_snapshot_claims_empty():
    cached = {
        "summary": "账户当前空仓，无历史盈亏记录。",
        "portfolio_snapshot": {"positions_count": 0},
        "top_signals": [{"symbol": "AAA"}],
    }

    assert CopilotService._morning_brief_cache_looks_stale(cached) is True
