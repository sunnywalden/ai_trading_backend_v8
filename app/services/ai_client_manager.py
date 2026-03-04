"""
AI 客户端管理器 - 统一管理多个 AI 提供商（OpenAI、DeepSeek）

功能：
1. 支持多个 AI 提供商（OpenAI 主力 + DeepSeek 兜底）
2. 自动降级：OpenAI 失败时切换到 DeepSeek
3. 熔断机制：临时屏蔽失败的提供商
4. 统一的调用接口

降级策略：OpenAI → DeepSeek → 规则引擎
"""

import asyncio
import logging
import time
import uuid
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum

from app.core.config import settings
from app.core.proxy import apply_proxy_env, ProxyConfig

logger = logging.getLogger(__name__)


class AIProvider(str, Enum):
    """AI 提供商枚举"""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"


# 全局客户端缓存
_clients: Dict[AIProvider, Any] = {}

# 提供商熔断器：记录临时不可用的提供商及其恢复时间
_provider_circuit_breaker: Dict[AIProvider, float] = {}


def _init_openai_client():
    """初始化 OpenAI 客户端"""
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured")
        return None
    
    try:
        from openai import AsyncOpenAI
        
        # 应用代理配置
        apply_proxy_env(
            ProxyConfig(
                enabled=settings.PROXY_ENABLED,
                http_proxy=settings.HTTP_PROXY,
                https_proxy=settings.HTTPS_PROXY,
                no_proxy=settings.NO_PROXY,
            )
        )
        
        if settings.OPENAI_API_BASE:
            client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            )
        else:
            client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            )
        
        logger.info("✅ OpenAI client initialized")
        return client
    except ImportError:
        logger.error("openai package not installed, run: pip install openai")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        return None


def _init_deepseek_client():
    """初始化 DeepSeek 客户端（使用 OpenAI SDK，兼容格式）"""
    if not settings.DEEPSEEK_ENABLED:
        logger.info("DeepSeek disabled in config")
        return None
    
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not configured")
        return None
    
    try:
        from openai import AsyncOpenAI
        
        # DeepSeek API 完全兼容 OpenAI 格式
        # reasoner 模式需要更长的超时时间
        timeout = getattr(settings, 'DEEPSEEK_TIMEOUT_SECONDS', 30)
        client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_API_BASE,
            timeout=timeout,
        )
        
        logger.info("✅ DeepSeek client initialized (base_url: %s, timeout: %ds)", settings.DEEPSEEK_API_BASE, timeout)
        return client
    except Exception as e:
        logger.error(f"Failed to initialize DeepSeek client: {e}")
        return None


def get_ai_client(provider: AIProvider = AIProvider.OPENAI):
    """
    获取指定 AI 提供商的客户端（懒加载 + 全局单例）
    
    Args:
        provider: AI 提供商
    
    Returns:
        AsyncOpenAI 客户端实例，失败返回 None
    """
    global _clients
    
    # 检查熔断器
    if provider in _provider_circuit_breaker:
        recovery_time = _provider_circuit_breaker[provider]
        if datetime.now().timestamp() < recovery_time:
            remaining = int(recovery_time - datetime.now().timestamp())
            logger.warning(f"⚠️ {provider.value} is circuit-broken, recovery in {remaining}s")
            return None
        else:
            # 熔断恢复
            del _provider_circuit_breaker[provider]
            logger.info(f"✅ {provider.value} circuit breaker recovered")
    
    # 返回缓存的客户端
    if provider in _clients and _clients[provider]:
        return _clients[provider]
    
    # 初始化客户端
    if provider == AIProvider.OPENAI:
        _clients[provider] = _init_openai_client()
    elif provider == AIProvider.DEEPSEEK:
        _clients[provider] = _init_deepseek_client()
    else:
        logger.error(f"Unknown AI provider: {provider}")
        return None
    
    return _clients[provider]


def circuit_break_provider(provider: AIProvider, duration_seconds: int = 300):
    """
    熔断指定提供商（临时屏蔽）
    
    Args:
        provider: AI 提供商
        duration_seconds: 熔断时长（秒），默认 5 分钟
    """
    recovery_time = datetime.now().timestamp() + duration_seconds
    _provider_circuit_breaker[provider] = recovery_time
    logger.warning(f"🔴 Circuit breaking {provider.value} for {duration_seconds}s")


def get_model_for_provider(provider: AIProvider) -> str:
    """
    获取指定提供商的默认模型名
    
    Args:
        provider: AI 提供商
    
    Returns:
        模型名称
    """
    if provider == AIProvider.OPENAI:
        return settings.OPENAI_MODEL
    elif provider == AIProvider.DEEPSEEK:
        return settings.DEEPSEEK_MODEL
    else:
        return "gpt-4"


async def call_ai_with_fallback(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[AIProvider]]:
    """
    调用 AI 生成回复（带自动降级）

    降级顺序：基于 settings.AI_PROVIDERS 和 settings.AI_PREFERRED_PROVIDER 配置

    Args:
        messages: 消息列表 [{"role": "user", "content": "..."}]
        temperature: 温度参数
        max_tokens: 最大 token 数
        response_format: 响应格式（例如 {"type": "json_object"}）

    Returns:
        (生成的文本, 使用的提供商) 或 (None, None)
    """
    max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS

    # 1. 获取配置的提供商列表
    configured_providers = settings.AI_PROVIDERS
    preferred_provider = settings.AI_PREFERRED_PROVIDER

    # 如果是字符串（由于环境变量读取可能未被 Pydantic 自动解析为 list）
    if isinstance(configured_providers, str):
        configured_providers = [p.strip() for p in configured_providers.split(",")]

    # 2. 转换为枚举并根据首选性排序
    providers = []
    for p_name in configured_providers:
        try:
            providers.append(AIProvider(p_name.lower().strip()))
        except ValueError:
            logger.warning(f"Unknown AI provider in settings: {p_name}")

    if preferred_provider:
        try:
            pref_enum = AIProvider(preferred_provider.lower().strip())
            if pref_enum in providers:
                providers.remove(pref_enum)
                providers.insert(0, pref_enum)
        except ValueError:
            pass

    # 3. 如果列表为空，提供默认回退
    if not providers:
        providers = [AIProvider.OPENAI, AIProvider.DEEPSEEK]
    
    # 调试日志：输出最终尝试的提供商顺序（使用 warning 级别确保可见）
    logger.warning(f"🔍 AI Providers sequence: {[p.value for p in providers]}")

    last_error = None

    for provider in providers:
        # 特外检查 DeepSeek 是否在配置中被禁用
        if provider == AIProvider.DEEPSEEK and not settings.DEEPSEEK_ENABLED:
            logger.warning("⏩ DeepSeek is disabled, skipping")
            continue

        client = get_ai_client(provider)
        if not client:
            logger.warning(f"⚠️ {provider.value} client is None, skipping")
            continue

        model = get_model_for_provider(provider)
        logger.warning(f"🤖 Calling {provider.value} (model: {model})")

        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }

            # deepseek-reasoner: temperature/top_p 等参数无效但不会报错，保留兼容性
            # 但 response_format (JSON Output) 是被官方支持的，不要剥离
            if provider == AIProvider.DEEPSEEK and "reasoner" in model.lower():
                # reasoner 模式：temperature 无效，不传以保持简洁
                logger.warning(f"ℹ️ Using {model} (reasoner mode): temperature ignored per API docs")
            else:
                kwargs["temperature"] = temperature

            if response_format:
                kwargs["response_format"] = response_format

            response = await client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            content = message.content
            
            # 记录 DeepSeek 的推理过程（如果存在）
            reasoning = getattr(message, 'reasoning_content', None)
            if reasoning:
                logger.info(f"AI Provider ({provider.value}) reasoning extracted | length: {len(reasoning)}")
            
            # ★ 关键修复：DeepSeek R1 有时 content 为空，但 reasoning_content 中包含有效内容
            # 尝试从 reasoning_content 中提取 JSON 或有用文本
            if (not content or not content.strip()) and reasoning:
                logger.warning(f"AI Provider ({provider.value}) empty content, recovering from reasoning...")
                import re
                # 优先尝试从 reasoning 中提取 JSON
                json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', reasoning, re.DOTALL)
                if json_match:
                    content = json_match.group(1).strip()
                    logger.info(f"AI Provider ({provider.value}) JSON recovered from reasoning | length: {len(content)}")
                else:
                    # 非 JSON 场景：取 reasoning 最后一段作为结论
                    paragraphs = [p.strip() for p in reasoning.split('\n\n') if p.strip()]
                    if paragraphs:
                        content = paragraphs[-1]
                        logger.info(f"AI Provider ({provider.value}) text recovered from reasoning | length: {len(content)}")
            
            # 强化处理：DeepSeek 即使在非 JSON 模式下也可能返回 <think> 块，应始终将其剥离
            if content and provider == AIProvider.DEEPSEEK:
                if "<think>" in content and "</think>" in content:
                    logger.debug(f"AI Provider ({provider.value}) stripping <think> block")
                    content = content.split("</think>")[-1].strip()

            # 如果请求了 JSON 格式，进一步清理内容（处理 Markdown 代码块等）
            if content and response_format and response_format.get("type") == "json_object":
                # 1. 移除 Markdown 代码块
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    # 有时候 AI 不写 json 标签，只写 ```
                    parts = content.split("```")
                    if len(parts) >= 3:
                        # 取中间的部分
                        content = parts[1].strip()
                
                # 3. 兜底：如果还是不像 JSON，尝试提取第一个 { 到最后一个 } 之间的内容
                if content and not (content.startswith("{") and content.endswith("}")):
                    import re
                    match = re.search(r"(\{.*\})", content, re.DOTALL)
                    if match:
                        logger.debug(f"AI Provider ({provider.value}) JSON regex extraction used")
                        content = match.group(1).strip()

            # ★ 如果最终 content 仍为空，视为本次调用失败，继续尝试下一个 provider
            if not content or not content.strip():
                logger.warning(f"AI Provider ({provider.value}) failed to yield valid content")
                last_error = Exception(f"{provider.value} returned empty content")
                continue

            logger.info(f"AI Provider ({provider.value}) success | model: {model} | length: {len(content)}")
            return content, provider

        except Exception as e:
            error_str = str(e)
            logger.error(f"AI Provider ({provider.value}) error | model: {model} | {error_str}")
            last_error = e

            # 检查是否由于超时（有些超时错误不带 429 等状态码）
            is_timeout = "timeout" in error_str.lower() or "deadline" in error_str.lower()
            
            # 检查是否需要熔断（429 配额不足、401 认证失败）
            if "429" in error_str or "insufficient_quota" in error_str:
                circuit_break_provider(provider, duration_seconds=600)  # 熔断 10 分钟
            elif "401" in error_str or "authentication" in error_str.lower():
                circuit_break_provider(provider, duration_seconds=1800)  # 熔断 30 分钟
            elif is_timeout and provider == AIProvider.OPENAI:
                # OpenAI 超时通常是网络或代理问题，熔断一会以切换到备用
                circuit_break_provider(provider, duration_seconds=120)

            # 继续尝试下一个提供商
            continue

    # 所有提供商都失败
    if last_error:
        logger.error(f"All AI providers failed. Last error from {providers[-1].value if providers else 'unknown'}: {last_error}")
    return None, None


async def get_available_providers() -> List[AIProvider]:
    """
    获取当前可用的 AI 提供商列表

    Returns:
        可用提供商列表
    """
    available = []

    # 检查 OpenAI
    if get_ai_client(AIProvider.OPENAI):
        available.append(AIProvider.OPENAI)

    # 检查 DeepSeek
    if settings.DEEPSEEK_ENABLED and get_ai_client(AIProvider.DEEPSEEK):
        available.append(AIProvider.DEEPSEEK)

    return available


def get_circuit_breaker_status() -> Dict[str, Any]:
    """
    获取熔断器状态
    
    Returns:
        熔断器状态字典
    """
    now = datetime.now().timestamp()
    status = {}
    
    for provider, recovery_time in _provider_circuit_breaker.items():
        remaining = int(recovery_time - now)
        if remaining > 0:
            status[provider.value] = {
                "broken": True,
                "recovery_in_seconds": remaining,
            }
    
    return status


# ─────────────────────────────────────────────
# LLMCallGuard (V10.4 M1 T1.5)
# ─────────────────────────────────────────────
_LLM_CALL_TIMEOUT = 30   # 秒；超过此时间则超时熔断
_LLM_MAX_RETRIES  = 1    # 超时后最多重试次数（指数退避）


async def _write_llm_call_log(
    call_id: str,
    caller: str,
    model: str,
    latency_ms: int,
    status: str,
    degraded: bool,
    error_msg: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """异步写入 llm_call_log 表（fire-and-forget，不阻塞主流程）"""
    try:
        from app.models.db import SessionLocal
        from app.models.llm_call_log import LlmCallLog
        from sqlalchemy import insert

        async with SessionLocal() as session:
            await session.execute(
                insert(LlmCallLog).values(
                    call_id=call_id,
                    caller=caller,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    status=status,
                    degraded=degraded,
                    error_msg=error_msg,
                )
            )
            await session.commit()
    except Exception as exc:
        logger.debug(f"[LLMCallGuard] 写入 llm_call_log 失败（非阻塞忽略）: {exc}")


async def call_ai_guarded(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    caller: str = "unknown",
) -> Tuple[Optional[str], Optional[AIProvider]]:
    """
    LLMCallGuard 包装层（V10.4 M1 T1.5）

    在 call_ai_with_fallback 基础上增加：
    - 30s asyncio 超时保护（超时算 TIMEOUT 状态）
    - 指数退避重试一次
    - 全量调用日志写入 llm_call_log
    - degraded 标记（fallback 提供商被使用时）

    接口与 call_ai_with_fallback 完全兼容，可直接替换调用。
    """
    call_id = str(uuid.uuid4())
    start_ts = time.monotonic()
    preferred = _get_preferred_provider()

    content: Optional[str] = None
    used_provider: Optional[AIProvider] = None
    status = "ERROR"
    error_msg: Optional[str] = None

    for attempt in range(_LLM_MAX_RETRIES + 1):
        try:
            content, used_provider = await asyncio.wait_for(
                call_ai_with_fallback(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                ),
                timeout=_LLM_CALL_TIMEOUT,
            )
            if content:
                status = "SUCCESS"
                break
            else:
                status = "ERROR"
                error_msg = "empty_content"
        except asyncio.TimeoutError:
            status = "TIMEOUT"
            error_msg = f"timeout>{_LLM_CALL_TIMEOUT}s attempt={attempt+1}"
            logger.warning(f"[LLMCallGuard] {caller} 超时 (attempt {attempt+1}/{_LLM_MAX_RETRIES+1})")
            if attempt < _LLM_MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)   # 1s, 2s...
                continue
        except Exception as exc:
            status = "ERROR"
            error_msg = str(exc)[:200]
            logger.warning(f"[LLMCallGuard] {caller} 异常: {exc}")
            break

    latency_ms = int((time.monotonic() - start_ts) * 1000)
    degraded = (used_provider is not None and used_provider != preferred)
    model = get_model_for_provider(used_provider) if used_provider else "unknown"

    # fire-and-forget 写日志
    asyncio.ensure_future(
        _write_llm_call_log(
            call_id=call_id,
            caller=caller,
            model=model,
            latency_ms=latency_ms,
            status=status,
            degraded=degraded,
            error_msg=error_msg,
        )
    )

    return content, used_provider


def _get_preferred_provider() -> AIProvider:
    """返回当前配置中优先级最高的提供商"""
    preferred = getattr(settings, "AI_PREFERRED_PROVIDER", None)
    if preferred:
        try:
            return AIProvider(preferred.lower().strip())
        except ValueError:
            pass
    return AIProvider.OPENAI
