#!/usr/bin/env python3
"""校验并修复 execution_policy_profiles 数据一致性。

检查项：
1. orphan profiles：画像存在，但历史 execution_quality_log 已无法推导出该 key。
2. stale profiles：画像统计值与历史日志聚合结果不一致。
3. missing profiles：历史日志可推导，但画像表中缺失。
4. duplicate keys：同一维度键出现多行（理论上不应发生，常见于历史库未建唯一索引）。

默认仅检查；传 --execute 会删除异常 key 并按历史日志重建。
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

sys.path.insert(0, ROOT)

from app.core.config import settings  # noqa: E402
from scripts.maintenance.execution_policy_profile_common import (  # noqa: E402
    aggregate_profiles, compare_profile_payload, load_existing_profiles,
    load_source_rows, replace_profile_keys)


async def run_repair(
    *,
    execute: bool,
    account_id: str | None,
) -> None:
    from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                        create_async_engine)

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
            existing, duplicates = await load_existing_profiles(
                db, account_id=account_id
            )

            missing = sorted(set(expected) - set(existing))
            orphan = sorted(set(existing) - set(expected))
            stale = sorted(
                key
                for key in set(existing).intersection(expected)
                if not compare_profile_payload(
                    existing[key],
                    expected[key].payload,
                )
            )
            duplicate_keys = sorted(duplicates)
            repair_keys = sorted(
                set(missing + orphan + stale + duplicate_keys)
            )

            print(
                f"[repair] account_id={account_id!r} "
                f"existing={len(existing)} expected={len(expected)}"
            )
            print(
                f"[repair] missing={len(missing)} orphan={len(orphan)} "
                f"stale={len(stale)} duplicates={len(duplicate_keys)}"
            )

            if not execute:
                for label, keys in {
                    "missing": missing,
                    "orphan": orphan,
                    "stale": stale,
                    "duplicate": duplicate_keys,
                }.items():
                    for key in keys[:5]:
                        print(f"[dry-run] {label}: {key}")
                return

            deleted, inserted = await replace_profile_keys(
                db,
                keys=repair_keys,
                expected=expected,
            )
            print(
                f"[repair] ✓ repaired_keys={len(repair_keys)} "
                f"deleted_rows={deleted} inserted_rows={inserted}"
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair execution policy profiles"
    )
    parser.add_argument("--execute", action="store_true", help="Apply repair")
    parser.add_argument(
        "--account-id",
        default=None,
        help="Only repair one account",
    )
    args = parser.parse_args()
    asyncio.run(run_repair(execute=args.execute, account_id=args.account_id))


if __name__ == "__main__":
    main()

