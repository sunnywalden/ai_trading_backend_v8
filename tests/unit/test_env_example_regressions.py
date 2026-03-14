from pathlib import Path

import pytest


def test_env_example_idle_capital_headroom_factor_uses_scalar_dotenv_syntax():
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    content = env_example.read_text(encoding="utf-8")

    assert "IDLE_CAPITAL_GEA_HEADROOM_FACTOR = (" not in content

    for line in content.splitlines():
        if line.strip().startswith("IDLE_CAPITAL_GEA_HEADROOM_FACTOR"):
            value = line.split("=", 1)[1].split("#", 1)[0].strip()
            assert float(value) == pytest.approx(0.8)
            return

    pytest.fail("IDLE_CAPITAL_GEA_HEADROOM_FACTOR is missing from .env.example")
