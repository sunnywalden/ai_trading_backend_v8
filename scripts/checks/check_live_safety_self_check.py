#!/usr/bin/env python3
"""Live Safety 自检脚本。

用途：
- 检查 Live Safety freshness 矩阵
- 可选触发一次技术指标刷新任务
- 运行与 Live Safety 直接相关的关键健康检查
- 输出人类可读摘要或 JSON，便于人工排查和自动化集成
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.jobs.data_refresh_jobs import refresh_technical_indicators_job
from app.models.db import SessionLocal, close_db_resources
from app.services.autonomy_health_monitor import autonomy_health_monitor
from app.services.data_freshness_guard_service import data_freshness_guard_service

DEFAULT_HEALTH_CHECKS = [
    "check_equity_snapshot",
    "check_plan_fsm_alignment",
    "check_market_data_lag",
    "check_signal_freshness",
]

_STATUS_ORDER = {
    "OK": 0,
    "WARN": 1,
    "WARNING": 1,
    "CRITICAL": 2,
    "ERROR": 3,
}

_STATUS_ICON = {
    "OK": "✅",
    "WARN": "⚠️",
    "WARNING": "⚠️",
    "CRITICAL": "❌",
    "ERROR": "💥",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Live Safety self-checks for freshness and key health signals.",
    )
    parser.add_argument(
        "--account-id",
        default=settings.TIGER_ACCOUNT,
        help="账户 ID，默认使用 settings.TIGER_ACCOUNT",
    )
    parser.add_argument(
        "--skip-refresh-job",
        action="store_true",
        help="跳过技术指标刷新任务，只读取当前状态",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="只检查 freshness 矩阵，不运行关键健康检查",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 结果，便于自动化消费",
    )
    parser.add_argument(
        "--fail-on",
        choices=["never", "warn", "critical"],
        default="critical",
        help="遇到何种等级返回非 0 退出码，默认 critical",
    )
    return parser.parse_args()


def _severity(status: str | None) -> int:
    return _STATUS_ORDER.get((status or "").upper(), 0)


def _icon(status: str | None) -> str:
    return _STATUS_ICON.get((status or "").upper(), "•")


def _should_fail(status: str, fail_on: str) -> bool:
    severity = _severity(status)
    if fail_on == "never":
        return False
    if fail_on == "warn":
        return severity >= _severity("WARN")
    return severity >= _severity("CRITICAL")


def _health_result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {
        "name": getattr(result, "name", "unknown"),
        "status": getattr(result, "status", "UNKNOWN"),
        "message": getattr(result, "message", ""),
        "detail": getattr(result, "detail", {}),
        "checked_at": getattr(result, "checked_at", ""),
    }


async def run_self_check(args: argparse.Namespace) -> dict[str, Any]:
    refresh_result: dict[str, Any] | None = None
    health_results: list[dict[str, Any]] = []

    try:
        if not args.skip_refresh_job:
            await refresh_technical_indicators_job()

        async with SessionLocal() as db:
            freshness = await data_freshness_guard_service.get_freshness_matrix(
                db,
                args.account_id,
            )

            if not args.skip_health:
                for check_name in DEFAULT_HEALTH_CHECKS:
                    check_fn = getattr(autonomy_health_monitor, check_name)
                    result = await check_fn(db)
                    health_results.append(_health_result_to_dict(result))

            summary_statuses = [freshness.get("overall_status", "OK")]
            summary_statuses.extend(item.get("status", "OK") for item in health_results)
            worst_status = (
                max(summary_statuses, key=_severity) if summary_statuses else "OK"
            )

            refresh_result = {
                "executed": not args.skip_refresh_job,
                "status": "SKIPPED" if args.skip_refresh_job else "DONE",
            }

            return {
                "account_id": args.account_id,
                "refresh_job": refresh_result,
                "freshness": freshness,
                "health_checks": health_results,
                "summary": {
                    "worst_status": worst_status,
                    "non_ok_freshness": [
                        item
                        for item in freshness.get("matrix", [])
                        if item.get("status") != "OK"
                    ],
                    "non_ok_health_checks": [
                        item for item in health_results if item.get("status") != "OK"
                    ],
                },
            }
    finally:
        await close_db_resources()


def print_human_report(report: dict[str, Any]) -> None:
    freshness = report["freshness"]
    summary = report["summary"]
    refresh_job = report["refresh_job"]

    print("=" * 88)
    print("🩺 Live Safety 自检报告")
    print("=" * 88)
    print(f"账户: {report['account_id']}")
    print(f"刷新任务: {refresh_job['status']}")
    print(
        f"Freshness 总状态: {_icon(freshness['overall_status'])} {freshness['overall_status']}"
        f" | 推荐动作: {freshness['recommended_action']}"
    )
    print(f"最严重状态: {_icon(summary['worst_status'])} {summary['worst_status']}")

    print("\n--- Freshness Matrix ---")
    for item in freshness.get("matrix", []):
        status = item.get("status", "UNKNOWN")
        print(
            f"{_icon(status)} {item['source']:16s} "
            f"status={status:8s} "
            f"age={item.get('age_hours')}h "
            f"last_seen={item.get('last_seen')}"
        )

    health_checks = report.get("health_checks", [])
    if health_checks:
        print("\n--- Key Health Checks ---")
        for item in health_checks:
            status = item.get("status", "UNKNOWN")
            print(
                f"{_icon(status)} {item.get('name', 'unknown'):24s} "
                f"{status:8s} {item.get('message', '')}"
            )

    non_ok_freshness = summary.get("non_ok_freshness", [])
    non_ok_health_checks = summary.get("non_ok_health_checks", [])
    if non_ok_freshness or non_ok_health_checks:
        print("\n--- Non-OK Details ---")
        for item in non_ok_freshness:
            print(f"[freshness] {item['source']}: {item['status']} -> {item}")
        for item in non_ok_health_checks:
            print(f"[health] {item['name']}: {item['status']} -> {item['message']}")
    else:
        print("\n✅ 所有 freshness / 关键健康检查均为 OK")

    print("=" * 88)


async def main() -> int:
    args = parse_args()
    report = await run_self_check(args)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(report)

    if _should_fail(report["summary"]["worst_status"], args.fail_on):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
