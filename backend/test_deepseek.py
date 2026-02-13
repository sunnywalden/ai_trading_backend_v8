"""Quick test: verify DeepSeek API connectivity"""
import asyncio
import os, sys

# ensure we can import app
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings

print("=== Config Check ===")
print(f"AI_PROVIDERS: {settings.AI_PROVIDERS}")
print(f"AI_PREFERRED_PROVIDER: {settings.AI_PREFERRED_PROVIDER}")
print(f"DEEPSEEK_ENABLED: {settings.DEEPSEEK_ENABLED}")
print(f"DEEPSEEK_API_KEY: {settings.DEEPSEEK_API_KEY[:10] if settings.DEEPSEEK_API_KEY else 'NONE'}...")
print(f"DEEPSEEK_API_BASE: {settings.DEEPSEEK_API_BASE}")
print(f"DEEPSEEK_MODEL: {settings.DEEPSEEK_MODEL}")
print(f"DEEPSEEK_TIMEOUT_SECONDS: {settings.DEEPSEEK_TIMEOUT_SECONDS}")
print(f"PROXY_ENABLED: {settings.PROXY_ENABLED}")
print(f"HTTPS_PROXY: {settings.HTTPS_PROXY}")
print(f"NO_PROXY: {settings.NO_PROXY}")
print()

# Apply proxy settings (same as app startup)
from app.core.proxy import apply_proxy_env, ProxyConfig
apply_proxy_env(ProxyConfig(
    enabled=settings.PROXY_ENABLED,
    http_proxy=settings.HTTP_PROXY,
    https_proxy=settings.HTTPS_PROXY,
    no_proxy=settings.NO_PROXY,
))
print(f"ENV HTTP_PROXY after apply: {os.environ.get('HTTP_PROXY', 'NOT SET')}")
print(f"ENV HTTPS_PROXY after apply: {os.environ.get('HTTPS_PROXY', 'NOT SET')}")
print(f"ENV NO_PROXY after apply: {os.environ.get('NO_PROXY', 'NOT SET')}")
print()

print("=== Init DeepSeek Client ===")
from app.services.ai_client_manager import get_ai_client, AIProvider
client = get_ai_client(AIProvider.DEEPSEEK)
print(f"DeepSeek client: {client}")
print(f"Client type: {type(client)}")
print()

if not client:
    print("!!! CLIENT IS NONE - DeepSeek client failed to initialize!")
    sys.exit(1)

print("=== Test DeepSeek API Call ===")

async def test():
    try:
        resp = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "Say hello in 3 words"}],
            max_tokens=50,
        )
        content = resp.choices[0].message.content
        reasoning = getattr(resp.choices[0].message, 'reasoning_content', None)
        print(f"SUCCESS! Response: {content}")
        if reasoning:
            print(f"Reasoning length: {len(reasoning)}")
    except Exception as e:
        print(f"FAILED! Error type: {type(e).__name__}")
        print(f"Error: {e}")

asyncio.run(test())
