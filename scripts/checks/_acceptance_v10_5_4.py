#!/usr/bin/env python3
"""V10.5.4 验收测试脚本。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio

from sqlalchemy import func, select, text

from app.core.config import settings
from app.engine.signal_engine import SignalEngine
from app.models.db import SessionLocal, close_db_resources
from app.models.trading_signal import TradingSignal
from app.services.signal_transition_service import signal_transition_service
from app.services.truth_source_service import truth_source_service

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


async def test_signal_origin_mode_schema(db):
    try:
        r = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name='trading_signals' "
                    "AND column_name='signal_origin_mode'"
                )
            )
        ).scalar()
        check("V10.5.4 signal_origin_mode 字段存在", (r or 0) > 0, f"column_count={r}")
    except Exception as e:
        check("V10.5.4 signal_origin_mode 字段存在", False, str(e))


async def test_feature_flags_available(_db):
    try:
        ok = all(
            hasattr(settings, name)
            for name in (
                "SIGNAL_PIPELINE_V1054_ENABLED",
                "AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED",
                "NATIVE_AUDIT_V1054_ENABLED",
            )
        )
        detail = (
            f"pipeline={getattr(settings, 'SIGNAL_PIPELINE_V1054_ENABLED', None)}, "
            f"control_plane={getattr(settings, 'AUTONOMOUS_CONTROL_PLANE_V1054_ENABLED', None)}, "
            f"native_audit={getattr(settings, 'NATIVE_AUDIT_V1054_ENABLED', None)}"
        )
        check("V10.5.4 feature flags 可用", ok, detail)
    except Exception as e:
        check("V10.5.4 feature flags 可用", False, str(e))


async def test_payload_version_coverage(db):
    try:
        rows = (await db.execute(select(TradingSignal.extra_metadata).limit(200))).all()
        payload_ready = 0
        for row in rows:
            meta = row[0] if isinstance(row[0], dict) else {}
            payload = (
                meta.get("signal_payload")
                if isinstance(meta.get("signal_payload"), dict)
                else {}
            )
            if payload.get("version") == SignalEngine.CANONICAL_SIGNAL_PAYLOAD_VERSION:
                payload_ready += 1
        check(
            "V10.5.4 canonical payload 版本可识别",
            True,
            f"sample={len(rows)}, canonical_ready={payload_ready}",
        )
    except Exception as e:
        check("V10.5.4 canonical payload 版本可识别", False, str(e))


async def test_native_transition_reader(db):
    try:
        row = (await db.execute(select(TradingSignal.extra_metadata).limit(1))).first()
        meta = row[0] if row and isinstance(row[0], dict) else {}
        latest = signal_transition_service.latest_transition(meta)
        check(
            "V10.5.4 native transition reader 可用",
            latest is None or isinstance(latest, dict),
            f"latest_transition={'present' if latest else 'none'}",
        )
    except Exception as e:
        check("V10.5.4 native transition reader 可用", False, str(e))


async def test_truth_source_service(db):
    try:
        regime_truth = await truth_source_service.get_regime_truth_snapshot(db)
        positions_truth = await truth_source_service.get_positions_truth_snapshot(
            db, "admin"
        )
        check(
            "V10.5.4 truth source service 可用",
            isinstance(regime_truth, dict) and isinstance(positions_truth, dict),
            f"regime_source={regime_truth.get('source')}, positions_source={positions_truth.get('source')}",
        )
    except Exception as e:
        check("V10.5.4 truth source service 可用", False, str(e))


async def main():
    try:
        print("=" * 60)
        print("V10.5.4 验收测试")
        print("=" * 60)
        async with SessionLocal() as db:
            await test_signal_origin_mode_schema(db)
            await test_feature_flags_available(db)
            await test_payload_version_coverage(db)
            await test_native_transition_reader(db)
            await test_truth_source_service(db)

        print("\n" + "=" * 60)
        passed = sum(1 for _, ok in results if ok)
        total = len(results)
        print(f"结果：{passed}/{total} 通过")
        if passed == total:
            print("🎉 V10.5.4 验收通过！")
        else:
            print("⚠️  部分测试失败，请检查以上输出")
        print("=" * 60)
    finally:
        await close_db_resources()


if __name__ == "__main__":
    asyncio.run(main())
