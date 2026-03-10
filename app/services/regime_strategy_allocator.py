"""V10.2-M1: 体制感知策略权重分配器（StrategyWeightAllocator）

订阅 REGIME_CHANGED 事件，根据新体制：
1. 更新 RiskGateService 的 VaR 倍数（立即生效，影响下一笔风控检查）
2. 将各策略类别的权重倍数写入 Redis（供量化闭环 Job 读取）
3. 记录体制切换日志

策略权重矩阵（倍数 relative to baseline=1.0）：
  策略类别 / 体制      BULL  BEAR  HVOL  MEAN  RNGE  CRIS
  ─────────────────── ────  ────  ────  ────  ────  ────
  趋势跟踪 (TREND)     1.3   0.4   0.6   0.7   0.5   0.3
  动量 (MOMENTUM)      1.2   0.5   0.7   0.7   0.6   0.3
  均值回归 (MEAN_REV)  0.6   0.8   1.0   1.4   1.3   0.5
  低波动 (LOW_VOL)     0.8   1.1   1.2   1.2   1.3   1.4
  多因子 (FACTOR)      1.1   0.7   0.8   0.9   0.9   0.5
  防御 (DEFENSIVE)     0.7   1.4   1.3   1.0   1.0   1.5
  成长股 (GROWTH)      1.2   0.4   0.7   0.8   0.6   0.2
  价值股 (VALUE)       0.9   1.0   0.9   1.1   1.0   0.8
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.event_bus import event_bus, Topics
from app.services.risk_gate_service import RiskGateService

logger = logging.getLogger(__name__)

# Redis key 用于存储当前体制权重倍数
REDIS_REGIME_WEIGHTS_KEY = "regime:strategy_weights"
REDIS_REGIME_CURRENT_KEY = "regime:current"


# ─────────────────────────────────────────────────────────────────────────────
# 策略权重矩阵
# ─────────────────────────────────────────────────────────────────────────────
#   key: 策略 style 字段值（与 Strategy.style 对应）
#   BULL_TREND / BEAR_TREND / HIGH_VOL / MEAN_REVERT / RANGE_BOUND / CRISIS
_STRATEGY_WEIGHT_MATRIX: dict[str, dict[str, float]] = {
    "TREND": {
        "BULL_TREND": 1.3, "BEAR_TREND": 0.4, "HIGH_VOL": 0.6,
        "MEAN_REVERT": 0.7, "RANGE_BOUND": 0.5, "CRISIS": 0.3,
    },
    "MOMENTUM": {
        "BULL_TREND": 1.2, "BEAR_TREND": 0.5, "HIGH_VOL": 0.7,
        "MEAN_REVERT": 0.7, "RANGE_BOUND": 0.6, "CRISIS": 0.3,
    },
    "MEAN_REV": {
        "BULL_TREND": 0.6, "BEAR_TREND": 0.8, "HIGH_VOL": 1.0,
        "MEAN_REVERT": 1.4, "RANGE_BOUND": 1.3, "CRISIS": 0.5,
    },
    "LOW_VOL": {
        "BULL_TREND": 0.8, "BEAR_TREND": 1.1, "HIGH_VOL": 1.2,
        "MEAN_REVERT": 1.2, "RANGE_BOUND": 1.3, "CRISIS": 1.4,
    },
    "FACTOR": {
        "BULL_TREND": 1.1, "BEAR_TREND": 0.7, "HIGH_VOL": 0.8,
        "MEAN_REVERT": 0.9, "RANGE_BOUND": 0.9, "CRISIS": 0.5,
    },
    "DEFENSIVE": {
        "BULL_TREND": 0.7, "BEAR_TREND": 1.4, "HIGH_VOL": 1.3,
        "MEAN_REVERT": 1.0, "RANGE_BOUND": 1.0, "CRISIS": 1.5,
    },
    "GROWTH": {
        "BULL_TREND": 1.2, "BEAR_TREND": 0.4, "HIGH_VOL": 0.7,
        "MEAN_REVERT": 0.8, "RANGE_BOUND": 0.6, "CRISIS": 0.2,
    },
    "VALUE": {
        "BULL_TREND": 0.9, "BEAR_TREND": 1.0, "HIGH_VOL": 0.9,
        "MEAN_REVERT": 1.1, "RANGE_BOUND": 1.0, "CRISIS": 0.8,
    },
}


def get_regime_strategy_weights(regime: str) -> dict[str, float]:
    """
    返回给定体制下各策略类别的权重倍数字典。

    Parameters
    ----------
    regime : str  —  如 "BULL_TREND"

    Returns
    -------
    dict {style -> multiplier}
    """
    regime = regime.upper()
    result: dict[str, float] = {}
    for style, mapping in _STRATEGY_WEIGHT_MATRIX.items():
        result[style] = mapping.get(regime, 1.0)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 事件处理器
# ─────────────────────────────────────────────────────────────────────────────

# 全局 RiskGateService 实例（延迟初始化，无数据库依赖）
_risk_gate_svc = RiskGateService()


async def sync_regime_runtime_state(
    curr_regime: str,
    confidence: float = 0.0,
    var_multiplier: float = 1.0,
) -> None:
    """同步当前体制到 RiskGate 与 Redis，供运行时组件统一读取。"""
    curr_regime = str(curr_regime or "RANGE_BOUND").upper()

    # 1) RiskGate 内存态
    try:
        _risk_gate_svc.set_regime_var_multiplier(curr_regime)
        logger.info(
            f"[StrategyAllocator] VaR multiplier updated: ×{var_multiplier:.2f} for {curr_regime}"
        )
    except Exception as exc:
        logger.error(f"[StrategyAllocator] Failed to update VaR multiplier: {exc}")

    # 2) Redis 运行态
    try:
        from app.models.db import redis_client  # 延迟导入避免循环

        if not redis_client:
            return

        weights = get_regime_strategy_weights(curr_regime)

        pipe = redis_client.pipeline()
        pipe.set(REDIS_REGIME_WEIGHTS_KEY, json.dumps(weights), ex=86400 * 7)
        pipe.set(
            REDIS_REGIME_CURRENT_KEY,
            json.dumps(
                {
                    "regime": curr_regime,
                    "confidence": confidence,
                    "var_multiplier": var_multiplier,
                }
            ),
            ex=86400 * 7,
        )
        await pipe.execute()
        logger.info(
            f"[StrategyAllocator] Redis updated: weights={weights}, regime={curr_regime}"
        )
    except Exception as exc:
        logger.error(f"[StrategyAllocator] Failed to write to Redis: {exc}", exc_info=True)


async def on_regime_changed(payload: dict[str, Any]) -> None:
    """
    处理 REGIME_CHANGED 事件：
    1. 更新 RiskGateService 的 VaR 倍数
    2. 将权重矩阵写入 Redis（供闭环 Job 读取）
    3. 记录日志
    """
    curr_regime: str  = payload.get("curr", "RANGE_BOUND")
    prev_regime: str  = payload.get("prev") or "N/A"
    confidence: float = payload.get("confidence", 0.0)
    var_multiplier: float = payload.get("var_multiplier", 1.0)

    logger.info(
        f"[StrategyAllocator] Handling REGIME_CHANGED: {prev_regime} → {curr_regime} "
        f"(confidence={confidence:.2%}, var_multiplier={var_multiplier:.2f})"
    )
    await sync_regime_runtime_state(
        curr_regime=curr_regime,
        confidence=confidence,
        var_multiplier=var_multiplier,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 注册函数（在 main.py lifespan 中调用）
# ─────────────────────────────────────────────────────────────────────────────

def register_handlers() -> None:
    """向 EventBus 注册所有体制感知处理器。调用后立即生效。"""
    event_bus.subscribe(Topics.REGIME_CHANGED, on_regime_changed)
    logger.info("[StrategyAllocator] Registered REGIME_CHANGED handler on EventBus")


# ─────────────────────────────────────────────────────────────────────────────
# Redis 读取工具（供 Router 和量化 Job 使用）
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_regime_weights_from_redis() -> dict[str, float]:
    """
    从 Redis 读取当前体制下的策略权重倍数。
    若 Redis 不可达或 key 不存在，返回 baseline(全 1.0)。
    """
    try:
        from app.models.db import redis_client

        raw = await redis_client.get(REDIS_REGIME_WEIGHTS_KEY)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning(f"[StrategyAllocator] Redis read failed: {exc}")

    # Fallback：无差别权重
    return {style: 1.0 for style in _STRATEGY_WEIGHT_MATRIX}


async def fetch_current_regime_from_redis() -> dict:
    """从 Redis 读取当前体制摘要。"""
    try:
        from app.models.db import redis_client

        raw = await redis_client.get(REDIS_REGIME_CURRENT_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"regime": "UNKNOWN", "confidence": 0.0, "var_multiplier": 1.0}
