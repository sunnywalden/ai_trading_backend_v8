from types import SimpleNamespace

import pytest

from app.services.decision_post_mortem_service import DecisionPostMortemService


class _FakeSession:
    def __init__(self, pm):
        self._pm = pm
        self.flush_count = 0

    async def get(self, _model, _pm_id):
        return self._pm

    async def flush(self):
        self.flush_count += 1


def test_result_indicates_failure_for_fallback_payload():
    assert (
        DecisionPostMortemService._result_indicates_failure(
            {
                "factual_summary": "Auto-analysis failed: timeout",
                "key_lessons": "Analysis generation failed. Review manually.",
            }
        )
        is True
    )


@pytest.mark.asyncio
async def test_process_post_mortem_marks_failed_and_skips_lesson_insight(monkeypatch):
    service = DecisionPostMortemService()
    pm = SimpleNamespace(
        id=1,
        trade_id="journal:1",
        status="running",
        factual_summary=None,
        counterfactual_buy=None,
        counterfactual_hold=None,
        counterfactual_sell=None,
        key_lessons=None,
        improvement_suggestions=None,
        pattern_tags=None,
        error_category=None,
        cognitive_bias=None,
        reasoning_tokens=None,
        generation_latency_ms=None,
        insight_id=999,
    )
    db = _FakeSession(pm)

    async def _fake_reasoner(**_kwargs):
        return {
            "factual_summary": "Auto-analysis failed: upstream timeout",
            "counterfactual_buy": "",
            "counterfactual_hold": "",
            "counterfactual_sell": "",
            "key_lessons": "Analysis generation failed. Review manually.",
            "improvement_suggestions": "",
            "pattern_tags": [],
            "error_category": "unknown",
            "cognitive_bias": "unknown",
            "latency_ms": 321,
            "reasoning_tokens": 0,
        }

    async def _fail_if_called(*_args, **_kwargs):
        raise AssertionError(
            "lesson insight should not be created for failed post-mortem"
        )

    monkeypatch.setattr(service, "_call_deepseek_reasoner", _fake_reasoner)
    monkeypatch.setattr(service, "_create_lesson_insight", _fail_if_called)

    result = await service.process_post_mortem(
        db=db,
        pm_id=1,
        account_id="acc-1",
        symbol="NVDA",
        direction="BUY",
        entry_price=100.0,
        exit_price=95.0,
        realized_pnl=-5.0,
        hold_days=2,
        trade_context={},
    )

    assert result is pm
    assert pm.status == "failed"
    assert pm.key_lessons == "Analysis generation failed. Review manually."
    assert pm.insight_id is None
    assert db.flush_count == 1
