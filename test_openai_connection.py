#!/usr/bin/env python3
"""测试OpenAI API连接"""

import asyncio
import sys
sys.path.insert(0, 'backend')

from app.core.config import settings


async def test_openai():
    """测试OpenAI连接"""
    print("=" * 60)
    print("OpenAI API Connection Test")
    print("=" * 60)
    
    # 检查配置
    print(f"\n[Config]")
    print(f"  Model: {settings.OPENAI_MODEL}")
    print(f"  Timeout: {settings.OPENAI_TIMEOUT_SECONDS}s")
    print(f"  Max Tokens: {settings.OPENAI_MAX_TOKENS}")
    
    if not settings.OPENAI_API_KEY:
        print("\n❌ OPENAI_API_KEY not configured!")
        return
    
    print(f"  API Key: {settings.OPENAI_API_KEY[:20]}...{settings.OPENAI_API_KEY[-4:]}")
    
    # 尝试连接
    print(f"\n[Connection Test]")
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        print(f"  Testing with model: {settings.OPENAI_MODEL}")
        
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "user", "content": "Say 'Hello' in Chinese"}
            ],
            max_tokens=20,
            timeout=settings.OPENAI_TIMEOUT_SECONDS
        )
        
        content = response.choices[0].message.content
        print(f"  ✅ Connection successful!")
        print(f"  Response: {content}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"  ❌ Connection failed!")
        print(f"  Error: {error_msg}")
        
        if "API key" in error_msg or "Incorrect" in error_msg:
            print("\n💡 Suggestions:")
            print("  1. Check if API key is valid")
            print("  2. Verify API key at: https://platform.openai.com/api-keys")
        elif "timeout" in error_msg.lower():
            print("\n💡 Suggestions:")
            print("  1. Check network connection")
            print("  2. In China, you need a proxy to access OpenAI")
            print("  3. Increase OPENAI_TIMEOUT_SECONDS in .env (current: 30s)")
            print("  4. Set proxy: export https_proxy=http://your-proxy:port")
        elif "model" in error_msg.lower():
            print("\n💡 Suggestions:")
            print(f"  1. Model '{settings.OPENAI_MODEL}' may not be available")
            print("  2. Try: gpt-3.5-turbo or gpt-4")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_openai())
