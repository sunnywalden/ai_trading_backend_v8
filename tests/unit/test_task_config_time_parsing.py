from app.jobs.task_config_jobs import _parse_daily_time
from app.services.task_config_service import normalize_trigger_time


def test_normalize_trigger_time_accepts_legacy_hour_only_format():
    assert normalize_trigger_time("DAILY", "20") == "20:00"
    assert normalize_trigger_time("DAILY", "8") == "08:00"


def test_normalize_trigger_time_accepts_compact_hhmm_format():
    assert normalize_trigger_time("DAILY", "930") == "09:30"
    assert normalize_trigger_time("DAILY", "2030") == "20:30"


def test_normalize_trigger_time_rejects_invalid_daily_values():
    assert normalize_trigger_time("DAILY", "25") is None
    assert normalize_trigger_time("DAILY", "20:99") is None
    assert normalize_trigger_time("DAILY", "abc") is None


def test_parse_daily_time_uses_normalized_result():
    assert _parse_daily_time("20") == (20, 0)
    assert _parse_daily_time("09:15") == (9, 15)
