#!/usr/bin/env python3
"""安全清理 Tiger API Monitor 当天统计/错误缓存（默认 dry-run）。

用途：
- 清理系统监控中当天已累计的 Tiger 错误统计，便于验证修复后的新行为
- 仅影响 Redis 中 `api_monitor:Tiger:*` 相关键，不触碰其他 provider
- 默认不清 cooldown，避免刚修好的节流保护被误清

示例：
  .venv/bin/python scripts/maintenance/clear_tiger_api_monitor_today.py
  .venv/bin/python scripts/maintenance/clear_tiger_api_monitor_today.py --apply
  .venv/bin/python scripts/maintenance/clear_tiger_api_monitor_today.py --apply --include-cooldown
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.cache import cache
from app.models.db import redis_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理 Tiger API Monitor 当天统计/错误缓存（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正删除匹配 key；默认仅 dry-run")
    parser.add_argument("--include-cooldown", action="store_true", help="额外删除 Tiger cooldown key（默认保留）")
    return parser


def _today_keys() -> tuple[str, str, str]:
    now = datetime.now()
    return (
        now.strftime("%Y-%m-%d"),
        now.strftime("%Y-%m-%d-%H"),
        now.strftime("%Y-%m-%d-%H-%M"),
    )


def _build_patterns(*, include_cooldown: bool) -> list[str]:
    day_key, hour_key, minute_key = _today_keys()
    prefix = cache.prefix
    patterns = [
        f"{prefix}api_monitor:Tiger:day:{day_key}",
        f"{prefix}api_monitor:Tiger:day:success:{day_key}",
        f"{prefix}api_monitor:Tiger:day:error:{day_key}",
        f"{prefix}api_monitor:Tiger:status:success:{day_key}",
        f"{prefix}api_monitor:Tiger:status:error:{day_key}",
        f"{prefix}api_monitor:Tiger:hour:{hour_key}*",
        f"{prefix}api_monitor:Tiger:hour:success:{hour_key}*",
        f"{prefix}api_monitor:Tiger:hour:error:{hour_key}*",
        f"{prefix}api_monitor:Tiger:minute:{minute_key[:13]}*",
        f"{prefix}api_monitor:Tiger:minute:success:{minute_key[:13]}*",
        f"{prefix}api_monitor:Tiger:minute:error:{minute_key[:13]}*",
        f"{prefix}api_monitor:Tiger:endpoint:*:{day_key}",
        f"{prefix}api_monitor:Tiger:response_times:*",
        f"{prefix}api_monitor:Tiger:errors",
    ]
    if include_cooldown:
        patterns.append(f"{prefix}api_monitor:Tiger:cooldown")
    return patterns


async def _expand_patterns(patterns: Iterable[str]) -> list[str]:
    matched: set[str] = set()
    if not redis_client:
        return []
    for pattern in patterns:
        keys = await redis_client.keys(pattern)
        for key in keys:
            if isinstance(key, bytes):
                matched.add(key.decode())
            else:
                matched.add(str(key))
    return sorted(matched)


async def main() -> None:
    args = build_parser().parse_args()
    if not redis_client:
        print("Redis client unavailable; nothing to do.")
        return

    patterns = _build_patterns(include_cooldown=args.include_cooldown)
    keys = await _expand_patterns(patterns)

    print("=" * 72)
    print("Tiger API Monitor Cleanup")
    print("=" * 72)
    print(f"mode={'APPLY' if args.apply else 'DRY_RUN'}")
    print(f"include_cooldown={args.include_cooldown}")
    print(f"matched_keys={len(keys)}")
    for key in keys[:50]:
        print(f"  {key}")
    if len(keys) > 50:
        print(f"  ... (+{len(keys) - 50} more)")

    if not args.apply:
        print("\nDRY_RUN 完成；如需真正删除这些 Tiger 监控 key，请加 --apply。")
        return

    if keys:
        deleted = await redis_client.delete(*keys)
    else:
        deleted = 0
    print(f"\n✅ 已删除 {deleted} 个 Tiger API Monitor key。")


if __name__ == "__main__":
    asyncio.run(main())
