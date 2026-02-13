import csv
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.strategy_export_service import StrategyExportService


@pytest.mark.parametrize("risk_flags,expected", [
    ([], ""),
    (["VOLATILE"], "VOLATILE"),
    (("A", "B"), "A;B"),
])
def test_asset_row_format(risk_flags, expected):
    payload = {
        "symbol": "AAPL",
        "signal_strength": 88.123,
        "weight": 0.134,
        "risk_flags": risk_flags,
        "notes": "test note",
        "signal_dimensions": {
            "momentum": 0.9,
            "volume": 0.8,
            "sentiment": 0.7,
        },
    }
    row = StrategyExportService._asset_to_row(payload)
    assert row[0] == "AAPL"
    assert row[1] == "88.12"
    assert row[2] == "0.134"
    assert row[3] == expected
    assert row[4] == "test note"
    assert row[5] == 0.9
    assert row[6] == 0.8
    assert row[7] == 0.7


def test_write_assets_to_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_ROOT", str(tmp_path))
    service = StrategyExportService(session=None)
    file_path = service.dir / "strategy_run_dummy.csv"
    assets = [
        {
            "symbol": "AAPL",
            "signal_strength": 75.0,
            "weight": 0.1,
            "risk_flags": ["VOLATILE"],
            "notes": "auto",
            "signal_dimensions": {
                "momentum": 0.65,
                "volume": 0.55,
                "sentiment": 0.75,
            },
        },
        {
            "symbol": "MSFT",
            "signal_strength": 82.5,
            "weight": 0.08,
            "risk_flags": [],
            "notes": "auto",
            "signal_dimensions": {
                "momentum": 0.7,
                "volume": 0.6,
                "sentiment": 0.8,
            },
        },
    ]
    service._write_assets_to_csv(assets, file_path)
    assert file_path.exists()
    rows = list(csv.reader(file_path.open("r", encoding="utf-8")))
    assert rows[0] == ["symbol", "strength", "weight", "risk_flags", "notes", "momentum", "volume", "sentiment"]
    assert len(rows) == 3
