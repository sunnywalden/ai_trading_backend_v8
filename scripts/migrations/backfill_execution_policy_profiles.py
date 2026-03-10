#!/usr/bin/env python3
"""从历史 execution_quality_log 回填 V10.5.3 execution_policy_profiles。

说明：
1. 以 AutonomousExecutionIntent + ExecutionQualityLog 为唯一真相源。
2. 默认 dry-run，只打印统计。
3. --execute 会先删除目标范围内既有画像，再按历史日志完整重建，确保幂等。

示例：
  python scripts/migrations/backfill_execution_policy_profiles.py
  python scripts/migrations/backfill_execution_policy_profiles.py --execute
    python scripts/migrations/backfill_execution_policy_profiles.py \
            --execute --account-id 2127xxxx
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _venv_python_path() -> str:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return os.path.abspath(os.path.join(ROOT, ".venv", scripts_dir, exe_name))


def _ensure_sqlalchemy_available() -> None:
    if importlib.util.find_spec("sqlalchemy") is not None:
        return

    try:
        venv_python = _venv_python_path()
        same_python = os.path.abspath(sys.executable) == os.path.abspath(
            venv_python
        )
        if os.path.exists(venv_python) and not same_python:
            os.execv(venv_python, [venv_python, *sys.argv])

        raise SystemExit(
            "sqlalchemy 未安装。请先激活 .venv，或使用 .venv\\Scripts\\python.exe 运行该脚本。"
        )
    except OSError as exc:
        raise SystemExit(
            f"无法切换到项目 .venv 解释器：{exc}"
        ) from exc


_ensure_sqlalchemy_available()

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, ROOT)

from app.core.config import settings  # noqa: E402
from scripts.maintenance.execution_policy_profile_common import (  # noqa: E402
    aggregate_profiles, load_source_rows, replace_profiles)


async def run_backfill(
    *,
    execute: bool,
    account_id: str | None,
) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_factory() as db:
            rows = await load_source_rows(db, account_id=account_id)
            expected = aggregate_profiles(rows)
            print(
                f"[backfill] source_rows={len(rows)} "
                f"expected_profiles={len(expected)} "
                f"account_id={account_id!r} execute={execute}"
            )

            if not execute:
                sample = list(expected.values())[:5]
                for item in sample:
                    payload = item.payload
                    print(
                        "[dry-run] %s/%s/%s/%s/%s sample_size=%s bias=%s",
                        payload["account_id"],
                        payload["symbol"],
                        payload["side"],
                        payload["urgency_bucket"],
                        payload["algo_type"],
                        payload["sample_size"],
                        payload["feedback_bias"],
                    )
                return

            deleted, inserted = await replace_profiles(
                db,
                expected=expected,
                account_id=account_id,
            )
            print(
                f"[backfill] ✓ deleted_existing={deleted} "
                f"inserted_profiles={inserted}"
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill execution policy profiles"
    )
    parser.add_argument("--execute", action="store_true", help="Write changes")
    parser.add_argument(
        "--account-id",
        default=None,
        help="Only rebuild one account",
    )
    args = parser.parse_args()
    asyncio.run(run_backfill(execute=args.execute, account_id=args.account_id))


if __name__ == "__main__":
    main()
