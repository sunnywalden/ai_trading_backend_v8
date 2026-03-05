"""advance_stuck_plans.py — 一次性处理卡在 S12-S15 的计划

用法:
  # 预览（不写库）
  python scripts/advance_stuck_plans.py --dry-run

  # 实际执行（直接流转到规则允许的最终阶段）
  python scripts/advance_stuck_plans.py

  # 强制跳过等待时间，将 S12-S15 全部直接推到 S16
  python scripts/advance_stuck_plans.py --force-complete
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models.strategy  # noqa — 预加载关系
from app.models.db import SessionLocal
from app.services.post_trade_pipeline_service import post_trade_pipeline_service


async def main(dry_run: bool, force_complete: bool):
    async with SessionLocal() as db:
        if force_complete:
            # 强制模式：忽略等待时间，反复推进直到 S16
            print("=== Force-complete mode: advancing ALL S12-S15 plans to S16 ===")
            total_advanced = 0
            for _round in range(6):  # 最多 6 轮（S12→S13→S14→S15→S16，留余量）
                result = await post_trade_pipeline_service.advance_post_trade_plans(
                    db=db,
                    # 不传 account_id → 所有账户
                    dry_run=False,
                )
                # 强制模式覆盖：将 stage_entered_at 设为足够久远，使下轮也能推进
                # （service 本身已处理 flush，下轮查询会拿到新 stage）
                from sqlalchemy import select, update
                from app.models.trading_plan import TradingPlan
                from datetime import datetime, timezone, timedelta
                await db.execute(
                    update(TradingPlan)
                    .where(TradingPlan.pipeline_stage.in_([12, 13, 14, 15]))
                    .values(stage_entered_at=datetime.now(timezone.utc) - timedelta(hours=1))
                )
                await db.flush()

                advanced = result["advanced"]
                total_advanced += advanced
                print(f"  Round {_round+1}: advanced={advanced} repaired={result['repaired_orphans']} by_stage={result['by_stage']}")
                if advanced == 0:
                    break

            await db.commit()
            print(f"\nDone. Total advanced: {total_advanced}")

        else:
            result = await post_trade_pipeline_service.advance_post_trade_plans(
                db=db,
                dry_run=dry_run,
            )
            if not dry_run:
                await db.commit()

            print(f"\n{'[DRY-RUN] ' if dry_run else ''}Results:")
            print(f"  scanned:          {result['scanned']}")
            print(f"  repaired_orphans: {result['repaired_orphans']}")
            print(f"  advanced:         {result['advanced']}")
            from app.schemas.lifecycle import PIPELINE_STAGE_NAMES
            for stage, cnt in sorted(result['by_stage'].items()):
                print(f"  S{stage}({PIPELINE_STAGE_NAMES.get(stage,'?')}) → S{stage+1}: {cnt} plans")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="预览，不写库")
    parser.add_argument("--force-complete", action="store_true", help="强制将所有 S12-S15 推进到 S16")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, force_complete=args.force_complete))
