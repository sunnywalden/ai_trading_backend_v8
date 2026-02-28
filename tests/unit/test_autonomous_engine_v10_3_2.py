import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.services.autonomous_engine import AutonomousEngine
from app.models.execution_intent import AutonomousExecutionIntent


@pytest.mark.asyncio
async def test_execution_intent_idempotency_key_unique_enforced():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(AutonomousExecutionIntent.__table__.create)

    ae = AutonomousEngine()
    signal = {"id": 1, "signal_id": "sig-001", "symbol": "AAPL"}
    decision = {"symbol": "AAPL", "action": "BUY", "qty": 10}

    async with Session() as session:
        first = await ae._create_execution_intent(
            db=session,
            account_id="acc-1",
            signal=signal,
            decision=decision,
            status="PENDING",
            reason="unit-test",
        )
        second = await ae._create_execution_intent(
            db=session,
            account_id="acc-1",
            signal=signal,
            decision=decision,
            status="PENDING",
            reason="unit-test-duplicate",
        )

    await engine.dispose()

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_ai_decide_abs_shares_mode_fallback_uses_absolute_quantity(monkeypatch):
    ae = AutonomousEngine()

    async def _fake_call_ai(*args, **kwargs):
        return {"action": "HOLD", "symbol": "AAPL", "qty": 0, "reasoning": "mock hold"}

    monkeypatch.setattr(ae, "_call_ai", _fake_call_ai)

    signal = {
        "id": 10,
        "signal_id": "sig-abs-qty",
        "symbol": "AAPL",
        "signal_type": "ENTRY",
        "direction": "LONG",
        "confidence": 0.92,
        "quantity_mode": "ABS_SHARES",
        "quantity_value": 12,
    }
    positions = {
        "AAPL": {"market_price": 100.0}
    }

    decision = await ae._ai_decide(signal=signal, positions=positions, equity=100000.0)

    assert decision["action"] == "BUY"
    assert float(decision["qty"]) == 12.0
