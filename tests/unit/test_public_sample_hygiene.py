from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]
SENSITIVE_KEYS = {
    "MYSQL_PASSWORD",
    "TIGER_PRIVATE_KEY_PATH",
    "ADMIN_PASSWORD",
    "JWT_SECRET_KEY",
    "SEED_RESEARCHER_PASSWORD",
    "SEED_TRADER_PASSWORD",
    "SEED_SUPERVISOR_PASSWORD",
    "SEED_ADMIN_PASSWORD",
    "BROKER_CREDENTIAL_ENCRYPTION_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "FRED_API_KEY",
    "NEWS_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "REDIS_PASSWORD",
    "TIGER_ID",
}


def _assignments(text: str) -> list[tuple[str, str]]:
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        found.append((key, value))
    return found


def test_env_example_sensitive_values_are_empty():
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    seen = set()
    for key, value in _assignments(content):
        if key not in SENSITIVE_KEYS:
            continue
        seen.add(key)
        assert value == "", key
    missing = SENSITIVE_KEYS - seen
    assert not missing, sorted(missing)


def test_tracked_node_modules_are_absent_from_the_index():
    import subprocess

    tracked = subprocess.check_output(
        ["git", "ls-files", "node_modules"],
        cwd=REPO_ROOT,
        text=True,
    )
    assert tracked.strip() == ""


def test_settings_reject_missing_auth_secrets(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            AUTH_ENABLED=True,
            RBAC_V1121_ENABLED=False,
            ADMIN_PASSWORD=None,
            JWT_SECRET_KEY=None,
            DB_TYPE="sqlite",
        )


def test_settings_reject_placeholder_jwt_and_admin_password():
    with pytest.raises(ValidationError):
        Settings(
            AUTH_ENABLED=True,
            RBAC_V1121_ENABLED=False,
            ADMIN_PASSWORD="unit-test-admin-password",
            JWT_SECRET_KEY="change-me-please",
            DB_TYPE="sqlite",
        )
    with pytest.raises(ValidationError):
        Settings(
            AUTH_ENABLED=True,
            RBAC_V1121_ENABLED=False,
            ADMIN_PASSWORD="change-this-admin-password",
            JWT_SECRET_KEY="unit-test-jwt-secret",
            DB_TYPE="sqlite",
        )


def test_settings_have_no_builtin_database_password_or_private_redis_host(monkeypatch):
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.delenv("REDIS_HOST", raising=False)
    settings = Settings(
        AUTH_ENABLED=True,
        RBAC_V1121_ENABLED=False,
        ADMIN_PASSWORD="unit-test-admin-password",
        JWT_SECRET_KEY="unit-test-jwt-secret",
        DB_TYPE="sqlite",
    )
    assert settings.MYSQL_PASSWORD == ""
    assert settings.REDIS_HOST == "localhost"
    assert not settings.REDIS_HOST.startswith("192.168.")
    assert settings.JWT_SECRET_KEY == "unit-test-jwt-secret"


def test_mysql_mode_requires_a_password():
    with pytest.raises(ValidationError):
        Settings(
            AUTH_ENABLED=False,
            DB_TYPE="mysql",
            MYSQL_PASSWORD="",
            JWT_SECRET_KEY=None,
        )
