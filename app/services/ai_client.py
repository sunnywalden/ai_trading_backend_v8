"""ai_client.py — V10.3.3 AI 调用统一适配层

将 ai_client_manager.call_ai_with_fallback 封装为简单的 call_ai 接口，
供 multi_agent_orchestrator / decision_post_mortem_service 等模块使用。

接口：
    resp = await call_ai(model=..., messages=[...], max_tokens=...)
    content = resp["content"]           # str
    tokens  = resp["usage"]["total_tokens"]  # int
"""

from __future__ import annotations

from typing import Any

from app.services.ai_client_manager import call_ai_with_fallback


async def call_ai(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.7,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    统一 AI 调用接口。

    Parameters
    ----------
    model:      模型名称（当前忽略，由 ai_client_manager 路由）
    messages:   消息列表 [{"role": ..., "content": ...}]
    max_tokens: 最大 token 数
    temperature: 采样温度

    Returns
    -------
    dict 包含：
        content (str): 生成文本
        usage   (dict): {"total_tokens": int, "completion_tokens": int}
    """
    content, _provider = await call_ai_with_fallback(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return {
        "content": content or "",
        "usage": {
            "total_tokens": 0,
            "completion_tokens": 0,
        },
    }
