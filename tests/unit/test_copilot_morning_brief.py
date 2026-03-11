from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.copilot_service import CopilotService


@pytest.mark.asyncio
async def test_morning_brief_cache_self_heals_stale_positions(monkeypatch):
    service = CopilotService()
    slot_end = datetime(2026, 3, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

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

    async def fake_build_context(
        _account_id: str,
        context_account_id: str | None = None,
    ):
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
    monkeypatch.setattr(
        service,
        "_normalize_morning_brief_result",
        fake_normalize,
    )
    monkeypatch.setattr(
        service,
        "_get_morning_brief_slot",
        lambda _now=None: (
            "2026-03-11",
            slot_end - timedelta(hours=24),
            slot_end,
        ),
    )

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


@pytest.mark.asyncio
async def test_morning_brief_returns_quick_fallback_and_schedules_ai(
    monkeypatch,
):
    service = CopilotService()
    cache_writes = []
    scheduled = []
    slot_end = datetime(2026, 3, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    async def fake_resolve(_account_id: str) -> str:
        return "21272246230273657"

    async def fake_cache_get(_key: str):
        return None

    async def fake_cache_set(key: str, value, expire: int):
        cache_writes.append((key, value, expire))

    async def fake_build_context(
        _account_id: str, context_account_id: str | None = None
    ):
        return {
            "account_id": context_account_id or "21272246230273657",
            "date": "2026-03-11",
            "market_regime": "MEAN_REVERT",
            "autonomy_level": "SEMI",
            "positions_count": 3,
            "positions_preview": [
                {"symbol": "ORCL"},
                {"symbol": "QCOM"},
                {"symbol": "MSFT"},
            ],
            "top_signals": [
                {
                    "symbol": "GDRX",
                    "action": "SignalType.ENTRY",
                    "reason": "test",
                    "confidence": 0.98,
                }
            ],
            "factor_exposure": {
                "portfolio_beta": 1.0,
                "beta_mom": 0.2,
            },
            "pnl_ticker": {
                "unrealized_pnl_pct": 1.2,
                "top_contributor": "ORCL",
            },
        }

    def fake_schedule(
        cache_key: str,
        context: dict,
        slot_end=None,
    ):
        scheduled.append((cache_key, context["positions_count"]))

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError(
            "_call_ai should not block the foreground request"
        )

    monkeypatch.setattr(service, "_resolve_context_account_id", fake_resolve)
    monkeypatch.setattr(service, "_build_context", fake_build_context)
    monkeypatch.setattr(
        service,
        "_schedule_morning_brief_refresh",
        fake_schedule,
    )
    monkeypatch.setattr(service, "_call_ai", fail_if_called)
    monkeypatch.setattr(
        service,
        "_get_morning_brief_slot",
        lambda _now=None: (
            "2026-03-11",
            slot_end - timedelta(hours=24),
            slot_end,
        ),
    )

    from app.services import copilot_service as copilot_module

    monkeypatch.setattr(copilot_module.cache, "get", fake_cache_get)
    monkeypatch.setattr(copilot_module.cache, "set", fake_cache_set)

    result = await service.morning_brief("admin", force_refresh=False)

    assert result["portfolio_snapshot"]["positions_count"] == 3
    assert "账户当前持有 3 个标的" in result["summary"]
    assert scheduled == [("morning_brief:21272246230273657:2026-03-11", 3)]
    assert cache_writes


def test_morning_brief_slot_before_8_uses_previous_day():
    slot_day, slot_start, slot_end = CopilotService._get_morning_brief_slot(
        datetime(2026, 3, 11, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert slot_day == "2026-03-10"
    assert slot_start.hour == 8
    assert slot_end - slot_start == timedelta(hours=24)


@pytest.mark.asyncio
async def test_generate_and_cache_morning_brief_uses_slot_ttl(monkeypatch):
    service = CopilotService()
    cache_writes = []
    reference_time = datetime(
        2026,
        3,
        11,
        8,
        0,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )

    async def fake_resolve(_account_id: str) -> str:
        return "21272246230273657"

    async def fake_build_context(
        _account_id: str,
        context_account_id: str | None = None,
    ):
        return {
            "account_id": context_account_id or "21272246230273657",
            "date": "2026-03-11",
            "market_regime": "MEAN_REVERT",
            "positions_count": 2,
            "positions_preview": [{"symbol": "ORCL"}, {"symbol": "MSFT"}],
            "top_signals": [],
            "factor_exposure": {},
            "pnl_ticker": {},
        }

    async def fake_cache_get(_key: str):
        return None

    async def fake_cache_set(key: str, value, expire: int):
        cache_writes.append((key, value, expire))

    async def fake_generate(_context: dict):
        return {
            "date": "2026-03-11",
            "market_regime": "MEAN_REVERT",
            "summary": "test",
            "market_outlook": "test",
            "portfolio_snapshot": {"positions_count": 2},
            "key_themes": [],
            "top_signals": [],
            "risk_alerts": [],
        }

    monkeypatch.setattr(service, "_resolve_context_account_id", fake_resolve)
    monkeypatch.setattr(service, "_build_context", fake_build_context)
    monkeypatch.setattr(service, "_generate_morning_brief_with_ai", fake_generate)

    from app.services import copilot_service as copilot_module

    monkeypatch.setattr(copilot_module.cache, "get", fake_cache_get)
    monkeypatch.setattr(copilot_module.cache, "set", fake_cache_set)

    await service.generate_and_cache_morning_brief(
        "admin",
        force_refresh=True,
        prefer_quick=False,
        reference_time=reference_time,
    )

    assert cache_writes
    assert cache_writes[0][0] == "morning_brief:21272246230273657:2026-03-11"
    assert cache_writes[0][2] == 86400
