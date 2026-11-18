#!/usr/bin/env python3
"""测试 OpenAI API 连接

说明：该脚本位于 `tests/integration/`（集成测试）。
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

import pytest

from app.core.config import settings
from tests.external_calls import external_calls_enabled, require_external_calls

pytestmark = pytest.mark.skipif(
    not external_calls_enabled(),
    reason="opt-in LLM call; set RUN_EXTERNAL_INTEGRATION=1",
)


async def test_openai():
    require_external_calls()
    """测试 OpenAI 连接"""
    print("=" * 60)
    print("OpenAI API Connection Test")
    print("=" * 60)

    # 检查配置
    print("\n[Config]")
    print(f"  Model: {settings.OPENAI_MODEL}")
    print(f"  Timeout: {settings.OPENAI_TIMEOUT_SECONDS}s")
    print(f"  Max Tokens: {settings.OPENAI_MAX_TOKENS}")
    print(f"  OPENAI_API_BASE: {settings.OPENAI_API_BASE or '<unset>'}")
    print(f"  PROXY_ENABLED: {getattr(settings, 'PROXY_ENABLED', False)}")

    if not settings.OPENAI_API_KEY:
        print("\n❌ OPENAI_API_KEY not configured!")
        return

    print("  API Key: configured")

    # 尝试连接
    print("\n[Connection Test]")
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE or None,
        )

        print(f"  Testing with model: {settings.OPENAI_MODEL}")

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": "Say 'Hello' in Chinese"}],
            max_tokens=20,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )

        content = response.choices[0].message.content
        print("  ✅ Connection successful!")
        print(f"  Response: {content}")

    except Exception as e:
        error_msg = str(e)
        print("  ❌ Connection failed!")
        print(f"  Error: {error_msg}")

        if "API key" in error_msg or "Incorrect" in error_msg:
            print("\n💡 Suggestions:")
            print("  1. Check if API key is valid")
            print("  2. Verify API key at: https://platform.openai.com/api-keys")
        elif "timeout" in error_msg.lower():
            print("\n💡 Suggestions:")
            print("  1. Check network connection")
            print("  2. If needed, enable PROXY_ENABLED and set HTTP_PROXY/HTTPS_PROXY in .env")
            print("  3. Increase OPENAI_TIMEOUT_SECONDS in .env (default: 30s)")
        elif "model" in error_msg.lower():
            print("\n💡 Suggestions:")
            print(f"  1. Model '{settings.OPENAI_MODEL}' may not be available")
            print("  2. Try a different OPENAI_MODEL")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    require_external_calls()
    asyncio.run(test_openai())
