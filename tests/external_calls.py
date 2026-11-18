"""Opt-in gate for scripts that talk to brokers, market data, or LLM APIs."""

from __future__ import annotations

import os
import sys

ENV_VAR = "RUN_EXTERNAL_INTEGRATION"


def external_calls_enabled() -> bool:
    return os.environ.get(ENV_VAR) == "1"


def require_external_calls() -> None:
    if external_calls_enabled():
        return
    print(
        "Skipped: this script can call a broker, market-data service, or LLM. "
        f"Set {ENV_VAR}=1 to run it. The default test command does not.",
        file=sys.stderr,
    )
    raise SystemExit(2)
