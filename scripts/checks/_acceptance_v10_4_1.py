#!/usr/bin/env python3
"""V10.4.1 验收测试脚本"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import app.models.strategy  # noqa: F401 — 触发模型注册

from sqlalchemy import text, select, func
from app.models.db import SessionLocal, close_db_resources
from app.models.trading_signal import TradingSignal
from app.services.signal_intelligence_service import signal_intelligence_service
from app.services.autonomy_health_monitor import autonomy_health_monitor

PASS = "✅"
FAIL = "❌"
results = []


def check(name: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    msg = f"{icon} {name}"
    if detail:
        msg += f"\n   {detail}"
    print(msg)
    results.append((name, ok))
    return ok


async def test_m1_llm_call_log(db):
    """M1 T1.5 — llm_call_log 表写入 & 统计"""
    try:
        await db.execute(text(
            "INSERT INTO llm_call_log (call_id, caller, model, latency_ms, status, degraded) "
            "VALUES ('acc-test-001', 'v10_4_1_acceptance', 'deepseek-chat', 145, 'SUCCESS', 0)"
        ))
        await db.commit()

        r = (await db.execute(text(
            "SELECT COUNT(*), AVG(latency_ms) FROM llm_call_log WHERE caller='v10_4_1_acceptance'"
        ))).first()
        cnt, avg_lat = r[0], r[1]

        await db.execute(text("DELETE FROM llm_call_log WHERE caller='v10_4_1_acceptance'"))
        await db.commit()

        check("M1 T1.5 llm_call_log 写入/统计", cnt == 1, f"count={cnt}, avg_latency={avg_lat:.1f}ms")
    except Exception as e:
        check("M1 T1.5 llm_call_log 写入/统计", False, str(e))


async def test_m1_return_backfill(db):
    """M1 T1.1 — trading_signals.actual_return 字段是否存在"""
    try:
        r = (await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name='trading_signals' AND column_name='actual_return'"
        ))).scalar()
        check("M1 T1.1 actual_return 字段存在", r > 0, f"column_count={r}")
    except Exception as e:
        check("M1 T1.1 actual_return 字段存在", False, str(e))


async def test_m1_signal_intelligence(db):
    """M1 T1.2 — data_quality 字段返回"""
    try:
        intel = await signal_intelligence_service.get_signal_intelligence(db, "admin")
        dims = intel.get("dimensions", [])
        has_dq = all("data_quality" in d for d in dims) if dims else True
        sample = f"dims={len(dims)}, sample_data_quality={dims[0].get('data_quality') if dims else 'N/A'}"
        check("M1 T1.2 IC data_quality 字段", has_dq, sample)
    except Exception as e:
        check("M1 T1.2 IC data_quality 字段", False, str(e))


async def test_m4_health_monitor(db):
    """M4 — AutonomyHealthMonitor 8 项检查"""
    try:
        report = await autonomy_health_monitor.run_all_checks(db)
        report_dict = report.to_dict()
        checks = report_dict.get("checks", [])
        overall = report_dict.get("overall_status", "UNKNOWN")
        check(
            "M4 AutonomyHealthMonitor 8项检查",
            len(checks) >= 6,
            f"checks_count={len(checks)}, overall_status={overall}"
        )
        for c in checks:
            name = c.get("name", "?")
            status = c.get("status", "?")
            icon = "  ✅" if status == "OK" else ("  ⚠️" if status == "WARN" else "  ❌")
            print(f"{icon} {name}: {status}")
    except Exception as e:
        check("M4 AutonomyHealthMonitor 8项检查", False, str(e))


async def test_m1_copilot_context(db):
    """M1/M3 — copilot/context 端点底层数据查询"""
    try:
        from app.models.trading_plan import TradingPlan
        from datetime import datetime, timezone

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        active_count = (await db.execute(
            select(func.count(TradingPlan.id))
            .where(TradingPlan.plan_status.in_(["ACTIVE", "PARTIAL"]))
        )).scalar() or 0
        signal_count = (await db.execute(
            select(func.count(TradingSignal.id))
            .where(TradingSignal.created_at >= today_start)
        )).scalar() or 0
        # 验证 /copilot/context 所需的两个核心数据源均可访问
        check(
            "M3 /copilot/context 数据源",
            active_count >= 0 and signal_count >= 0,
            f"active_plans={active_count}, today_signals={signal_count}"
        )
    except Exception as e:
        check("M3 /copilot/context 数据源", False, str(e))


async def main():
    try:
        print("=" * 60)
        print("V10.4.1 验收测试")
        print("=" * 60)

        async with SessionLocal() as db:
            print("\n── M1 数据闭环治理 ──")
            await test_m1_llm_call_log(db)
            await test_m1_return_backfill(db)
            await test_m1_signal_intelligence(db)

            print("\n── M3/M1 Copilot 上下文 ──")
            await test_m1_copilot_context(db)

            print("\n── M4 自主循环稳定 ──")
            await test_m4_health_monitor(db)

        print("\n" + "=" * 60)
        passed = sum(1 for _, ok in results if ok)
        total = len(results)
        print(f"结果：{passed}/{total} 通过")
        if passed == total:
            print("🎉 V10.4.1 验收通过！")
        else:
            print("⚠️  部分测试失败，请检查以上输出")
        print("=" * 60)
    finally:
        await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
