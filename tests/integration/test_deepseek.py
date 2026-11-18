"""Manual DeepSeek connectivity check.

This module must be safe to import. It does not call the network unless
RUN_EXTERNAL_INTEGRATION=1 and the file is executed as a script.
"""

from __future__ import annotations

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tests.external_calls import require_external_calls


async def _call_deepseek() -> int:
    from app.core.config import settings
    from app.core.proxy import ProxyConfig, apply_proxy_env
    from app.services.ai_client_manager import AIProvider, get_ai_client

    print("=== Config Check ===")
    print(f"AI_PROVIDERS: {settings.AI_PROVIDERS}")
    print(f"AI_PREFERRED_PROVIDER: {settings.AI_PREFERRED_PROVIDER}")
    print(f"DEEPSEEK_ENABLED: {settings.DEEPSEEK_ENABLED}")
    print(
        "DEEPSEEK_API_KEY: "
        + ("configured" if settings.DEEPSEEK_API_KEY else "not configured")
    )
    print(f"DEEPSEEK_API_BASE: {settings.DEEPSEEK_API_BASE}")
    print(f"DEEPSEEK_MODEL: {settings.DEEPSEEK_MODEL}")
    print(f"DEEPSEEK_TIMEOUT_SECONDS: {settings.DEEPSEEK_TIMEOUT_SECONDS}")
    print(f"PROXY_ENABLED: {settings.PROXY_ENABLED}")

    apply_proxy_env(
        ProxyConfig(
            enabled=settings.PROXY_ENABLED,
            http_proxy=settings.HTTP_PROXY,
            https_proxy=settings.HTTPS_PROXY,
            no_proxy=settings.NO_PROXY,
        )
    )

    if not settings.DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY is not configured")
        return 1

    client = get_ai_client(AIProvider.DEEPSEEK)
    if not client:
        print("DeepSeek client failed to initialize")
        return 1

    try:
        resp = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "Say hello in 3 words"}],
            max_tokens=50,
        )
        content = resp.choices[0].message.content
        print("DeepSeek call completed")
        print(f"Response length: {len(content or '')}")
        return 0
    except Exception as exc:
        print(f"DeepSeek call failed: {type(exc).__name__}")
        return 1


def main() -> int:
    require_external_calls()
    return asyncio.run(_call_deepseek())


if __name__ == "__main__":
    sys.exit(main())
