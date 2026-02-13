#!/usr/bin/env python3
"""测试 AI 分析服务配置

说明：该脚本已从项目根目录归档到 scripts/test_scripts/。
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.core.config import settings
from app.services.ai_analysis_service import AIAnalysisService


async def test_ai_config():
    print("=" * 60)
    print("OpenAI Configuration Test")
    print("=" * 60)

    print("\n[1] Configuration from .env:")
    print(f"  OPENAI_API_KEY: {'✓ Configured' if settings.OPENAI_API_KEY else '✗ Not configured'}")
    if settings.OPENAI_API_KEY:
        print(f"  API Key (first 20 chars): {settings.OPENAI_API_KEY[:20]}...")
    print(f"  OPENAI_MODEL: {settings.OPENAI_MODEL}")
    print(f"  OPENAI_MAX_TOKENS: {settings.OPENAI_MAX_TOKENS}")
    print(f"  OPENAI_TIMEOUT_SECONDS: {settings.OPENAI_TIMEOUT_SECONDS}")
    print(f"  PROXY_ENABLED: {getattr(settings, 'PROXY_ENABLED', False)}")
    print(f"  HTTP_PROXY: {getattr(settings, 'HTTP_PROXY', None) or '<unset>'}")
    print(f"  HTTPS_PROXY: {getattr(settings, 'HTTPS_PROXY', None) or '<unset>'}")
    print(f"  NO_PROXY: {getattr(settings, 'NO_PROXY', None) or '<unset>'}")
    print(f"  OPENAI_API_BASE: {getattr(settings, 'OPENAI_API_BASE', None) or '<unset>'}")

    print("\n[2] AIAnalysisService initialization:")
    service = AIAnalysisService()
    print(f"  Client: {'✓ Initialized' if service.client else '✗ Not initialized'}")
    models = await service.models
    print(f"  Models (fallback order): {models}")
    print(f"  Max tokens: {service.max_tokens}")
    print(f"  Timeout: {service.timeout}s")

    print("\n[3] Testing GPT call (technical summary):")
    if service.client:
        try:
            test_data = {
                "trend": {"trend_direction": "UP", "trend_strength": 0.75},
                "momentum": {
                    "rsi": {"value": 65, "status": "NEUTRAL", "signal": "HOLD"},
                    "macd": {
                        "value": 0.5,
                        "signal_line": 0.3,
                        "histogram": 0.2,
                        "status": "BULLISH",
                    },
                },
            }

            summary = await service.generate_technical_summary("AAPL", test_data)

            if summary:
                print("  ✓ GPT call successful")
                print(f"  Response preview: {summary[:100]}...")
            else:
                print("  ✗ GPT call failed, using rule-based fallback")

        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
    else:
        print("  ⊗ Client not initialized, skipping test")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_ai_config())
