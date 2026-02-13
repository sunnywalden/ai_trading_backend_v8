"""Proxy utilities.

目标：通过配置统一管理 HTTP/HTTPS 代理，确保：
- OpenAI SDK（基于 httpx，默认 trust_env=True）可走代理
- fredapi（基于 requests）可走代理

实现方式：在应用启动阶段根据 Settings 写入/清理环境变量：
- HTTP_PROXY / HTTPS_PROXY / NO_PROXY
并同时写入小写版本（部分库/运行环境会读取小写变量）。

注意：为了“通过配置管理代理开关”，当 PROXY_ENABLED=false 时，会主动清理这些环境变量，
即使它们在进程启动前已经被设置。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool
    http_proxy: str | None
    https_proxy: str | None
    no_proxy: str | None


_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


def apply_proxy_env(cfg: ProxyConfig) -> None:
    """Apply proxy-related environment variables.

    - enabled=True: set env vars from cfg (skip unset values)
    - enabled=False: clear all proxy env vars (upper/lower)

    This is intentionally deterministic so a single config switch controls behavior.
    """

    if not cfg.enabled:
        cleared = []
        for k in _ENV_KEYS:
            if k in os.environ:
                os.environ.pop(k, None)
                cleared.append(k)
        if cleared:
            logger.info(f"Proxy disabled: cleared env vars: {', '.join(cleared)}")
        else:
            logger.info("Proxy disabled: no proxy env vars to clear")
        return

    # enabled
    if not cfg.http_proxy and not cfg.https_proxy:
        logger.warning(
            "PROXY_ENABLED=true but neither HTTP_PROXY nor HTTPS_PROXY is configured; "
            "requests/httpx may still bypass proxy."
        )

    def _set(k_upper: str, value: str | None) -> None:
        if not value:
            return
        os.environ[k_upper] = value
        os.environ[k_upper.lower()] = value

    _set("HTTP_PROXY", cfg.http_proxy)
    _set("HTTPS_PROXY", cfg.https_proxy)
    _set("NO_PROXY", cfg.no_proxy)

    masked_http = "<set>" if cfg.http_proxy else "<unset>"
    masked_https = "<set>" if cfg.https_proxy else "<unset>"
    no_proxy = cfg.no_proxy or "<unset>"
    logger.info(f"Proxy enabled: HTTP_PROXY={masked_http}, HTTPS_PROXY={masked_https}, NO_PROXY={no_proxy}")
