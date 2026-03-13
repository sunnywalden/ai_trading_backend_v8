from __future__ import annotations

import logging
from typing import Any, cast

from app.core.logging_config import setup_logging
from app.jobs.strategy_jobs import _maybe_trim_auto_scan_universe
from app.services.ai_analysis_service import AIAnalysisService


def test_setup_logging_clears_uvicorn_handlers_and_uses_propagation():
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers.clear()
    uvicorn_error.addHandler(logging.StreamHandler())
    uvicorn_error.propagate = False

    setup_logging()

    assert uvicorn_error.handlers == []
    assert uvicorn_error.propagate is True


def test_parse_json_object_response_handles_code_fence_and_wrapper_text():
    service = cast(Any, object.__new__(AIAnalysisService))
    raw = """下面是结果：\n```json\n{\n  \"summary\": \"组合整体中性偏积极\",\n  \"recommendations\": [\n    {\"type\": \"REBALANCE\", \"action\": \"适度调仓\", \"reason\": \"集中度略高\"}\n  ]\n}\n```\n请参考。"""

    parsed = service._parse_json_object_response(raw)

    assert parsed["summary"] == "组合整体中性偏积极"
    assert parsed["recommendations"][0]["type"] == "REBALANCE"


def test_auto_cycle_universe_trim_prioritizes_anchor_symbols():
    symbols = [f"{i:05d}" for i in range(1, 400)]

    trimmed = _maybe_trim_auto_scan_universe(
        symbols=symbols,
        market="HK",
        task_id="auto_cycle:run-1",
    )

    assert len(trimmed) == 120
    assert trimmed[:5] == ["00700", "09988", "03690", "01810", "09618"]
