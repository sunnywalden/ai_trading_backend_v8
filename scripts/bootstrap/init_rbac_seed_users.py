#!/usr/bin/env python3
"""Initialize V11.2.1 RBAC seed users.

要求环境变量：
- SEED_RESEARCHER_PASSWORD
- SEED_TRADER_PASSWORD
- SEED_SUPERVISOR_PASSWORD
- SEED_ADMIN_PASSWORD
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.models.db import SessionLocal, close_db_resources  # noqa: E402
from app.services.rbac_service import rbac_service  # noqa: E402

REQUIRED_ENV_VARS = [
    "SEED_RESEARCHER_PASSWORD",
    "SEED_TRADER_PASSWORD",
    "SEED_SUPERVISOR_PASSWORD",
    "SEED_ADMIN_PASSWORD",
]


async def main() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name, "").strip()]
    if missing:
        raise SystemExit("缺少种子账号密码环境变量: " + ", ".join(missing))

    async with SessionLocal() as session:
        await rbac_service.create_seed_users(
            session, rbac_service.seed_password_map_from_env()
        )

    print("✓ RBAC seed users initialized: researcher / trader / supervisor / admin")
    await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
