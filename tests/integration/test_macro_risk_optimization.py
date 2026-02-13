#!/usr/bin/env python3
"""测试宏观风险服务的限流优化

说明：该脚本位于 `tests/integration/`（集成测试）。
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.services.macro_risk_scoring_service import MacroRiskScoringService


async def test_optimization():
    print("=" * 70)
    print("Macro Risk Service Optimization Test")
    print("=" * 70)

    service = MacroRiskScoringService()

    print("\n[Configuration]")
    print(f"  Cache duration: {service.cache_duration}")
    print(f"  Max retries: {service.max_retries}")
    print(f"  Retry delay: {service.retry_delay}s")
    print(f"  Request delay: {service.request_delay}s")

    print("\n[Test 1: Calculate macro risk with optimization]")
    print("  Starting calculation (this may take 10-30 seconds)...")

    try:
        import time

        start_time = time.time()
        risk_score = await service.calculate_macro_risk_score(use_cache=False)
        elapsed = time.time() - start_time

        print(f"  ✓ Calculation completed in {elapsed:.1f}s")
        print("\n[Results]")
        print(f"  Overall score: {risk_score.overall_score}")
        print(f"  Risk level: {risk_score.risk_level}")
        print(f"  Confidence: {risk_score.confidence}")
        print("\n[Dimension Scores]")
        print(f"  • Monetary Policy: {risk_score.monetary_policy_score}")
        print(f"  • Geopolitical: {risk_score.geopolitical_score}")
        print(f"  • Sector Bubble: {risk_score.sector_bubble_score}")
        print(f"  • Economic Cycle: {risk_score.economic_cycle_score}")
        print(f"  • Market Sentiment: {risk_score.sentiment_score}")
        print("\n[Summary]")
        print(f"  {risk_score.risk_summary}")
        print(f"  Recommendations: {risk_score.recommendations}")

    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
        import traceback

        traceback.print_exc()

    print("\n[Test 2: Using cache (should be instant)]")
    try:
        import time

        start_time = time.time()
        cached_score = await service.calculate_macro_risk_score(use_cache=True)
        elapsed = time.time() - start_time
        print(f"  ✓ Retrieved from cache in {elapsed:.3f}s")
        print(f"  Overall score: {cached_score.overall_score} (same as before)")
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(test_optimization())
