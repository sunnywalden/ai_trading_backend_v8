"""V10.4.2: SignalQualityConfig — 信号质量门控统一配置

所有信号漏斗相关参数的单一配置来源（Single Source of Truth）。
支持：
  1. 环境变量读取（生产默认值）
  2. 运行时热更新（PATCH /api/v1/signals/quality-config）
  3. 体制自适应覆盖（CRISIS / HIGH_VOL 自动提升门槛）
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from app.core.config import ENV_FILE

logger = logging.getLogger(__name__)

# ── 体制自适应参数覆盖表 ───────────────────────────────────────────────────────
_REGIME_OVERRIDES: dict[str, dict[str, Any]] = {
    "BULL_TREND": {
        "conviction_threshold": 93,
        "resonance_min_dims": 2,
        "max_concurrent_positions": 8,
        "long_allowed": True,
        "short_allowed": True,
    },
    "SIDEWAYS": {
        "conviction_threshold": 95,
        "resonance_min_dims": 3,
        "max_concurrent_positions": 6,
        "long_allowed": True,
        "short_allowed": True,
    },
    "BEAR_TREND": {
        "conviction_threshold": 97,
        "resonance_min_dims": 5,
        "max_concurrent_positions": 4,
        "long_allowed": False,  # 仅 SHORT 或防御性标的
        "short_allowed": True,
    },
    "HIGH_VOL": {
        "conviction_threshold": 97,
        "resonance_min_dims": 5,
        "max_concurrent_positions": 3,
        "long_allowed": True,  # 允许做多，但需对冲
        "short_allowed": True,
    },
    "CRISIS": {
        "conviction_threshold": 99,
        "resonance_min_dims": 6,
        "max_concurrent_positions": 2,
        "long_allowed": False,  # CRISIS 期间关闭所有做多
        "short_allowed": True,
    },
}


class SignalQualityConfig(BaseSettings):
    """信号质量门控参数（Pydantic BaseSettings 支持环境变量读取）"""

    # ── 信号质量分级 ──────────────────────────────────────────────────────────────
    ELITE_SIGNAL_SCORE: int = Field(
        default=98,
        description="ELITE（精英级）信号最低质量分",
    )
    ELITE_SIGNAL_FLOOR: int = Field(
        default=90,
        description="ELITE 信号最低校准下界",
    )
    ELITE_MIN_ALIGNED_DIMS: int = Field(
        default=5,
        description="ELITE 信号最低同向维度数",
    )
    HIGH_QUALITY_SIGNAL_SCORE: int = Field(
        default=95,
        description="HIGH（高质量）信号最低质量分",
    )
    MEDIUM_QUALITY_SIGNAL_SCORE: int = Field(
        default=90,
        description="MEDIUM（中质量）信号最低质量分",
    )

    # ── 置信度门控 ──────────────────────────────────────────────────────────────
    SIGNAL_CONFIDENCE_THRESHOLD: int = Field(
        default=95,
        description="Conviction Score 最低门槛（0-100）",
    )
    SIGNAL_CONFIDENCE_FLOOR: int = Field(
        default=85,
        description="置信度校准下界最低要求（0-100）",
    )
    MIN_EXPECTED_SHARPE: float = Field(
        default=0.5,
        description="信号预期夏普比率下限",
    )

    # ── 多维共振要求 ──────────────────────────────────────────────────────────────
    SIGNAL_RESONANCE_MIN_DIMS: int = Field(
        default=4,
        description="最少同向维度数量（6维中，≥4 才允许通过 Layer 3）",
    )
    RESONANCE_REQUIRED_TECHNICAL: bool = Field(
        default=True,
        description="是否强制要求 technical 维度在同向列表中",
    )
    ANTI_RESONANCE_KILL: bool = Field(
        default=True,
        description="是否启用反共振一票否决（tech/fundamental 对立或 CRISIS 做多）",
    )

    # ── 组合级约束 ──────────────────────────────────────────────────────────────
    MAX_CONCURRENT_POSITIONS: int = Field(
        default=6,
        description="任意时刻最大并发持仓标的数",
    )
    MAX_DAILY_SIGNALS: int = Field(
        default=5,
        description="每个交易日最多推进至执行的信号数",
    )
    MAX_POSITION_CORRELATION: float = Field(
        default=0.70,
        description="新仓与现有持仓的最大允许相关系数",
    )

    # ── 流动性过滤 ──────────────────────────────────────────────────────────────
    MIN_ADV_THRESHOLD: float = Field(
        default=1_000_000.0,
        description="最小日均成交量（美元），低于此值过滤",
    )
    MIN_MARKET_CAP: float = Field(
        default=500_000_000.0,
        description="最小市值（美元），低于此值过滤",
    )

    # ── 体制自适应调节 ──────────────────────────────────────────────────────────
    HIGH_VOL_THRESHOLD_BUMP: int = Field(
        default=5,
        description="HIGH_VOL 体制下置信度阈值自动提升的点数",
    )
    CRISIS_LONG_BLOCK: bool = Field(
        default=True,
        description="CRISIS 体制下是否拒绝所有 LONG 信号",
    )

    # ── 幽灵交易 ───────────────────────────────────────────────────────────────
    GHOST_TRADE_MAX_DAYS: int = Field(
        default=10,
        description="幽灵交易最大追踪天数",
    )
    GHOST_TRADE_ENABLED: bool = Field(
        default=True,
        description="是否为被拒信号创建幽灵交易记录",
    )

    # ── V10.5.2: 席位竞争准入机制 ────────────────────────────────────────────────
    CAPACITY_REPLACEMENT_ENABLED: bool = Field(
        default=True,
        description="是否启用席位竞争准入机制（否则维持原有硬拒绝行为）",
    )
    CAPACITY_REPLACEMENT_DRY_RUN: bool = Field(
        default=False,
        description="席位竞争仅评估，不触发实际平仓或拒绝（观察模式）",
    )
    CAPACITY_REPLACEMENT_MAX_PER_CYCLE: int = Field(
        default=2,
        description="每个决策周期最多触发席位替换次数",
    )
    CAPACITY_REPLACEMENT_MIN_EDGE: float = Field(
        default=5.0,
        description="触发席位替换的最低得分优势（挑战者分 - 持仓分 ≥ 此值才替换）",
    )
    CAPACITY_MIN_HOLD_MINUTES: int = Field(
        default=30,
        description="持仓受保护的最小持有时间（分钟），新建持仓不参与竞争",
    )
    CAPACITY_REPLACEMENT_COOLDOWN_MINUTES: int = Field(
        default=120,
        description="同一持仓在被替换后的冷却期（分钟），冷却期内不参与竞争",
    )

    # ── V11.0.1: Conviction Threshold Softening
    # 门控参数 ──────────────────────────
    CONVICTION_SOFT_COMPOSITE_FLOOR: int = Field(
        default=96,
        description=(
            "阈值软化时 composite_score 的最低要求（独立维度，非 tier）；"
            "必须 ≥ 此值才允许软化，防止前置维度整体偏弱的信号通过"
        ),
    )
    CONVICTION_SOFT_RESONANCE_FLOOR: int = Field(
        default=80,
        description=(
            "阈值软化时 resonance_bonus 的最低要求（独立维度，非 tier）；"
            "与 CONVICTION_SOFT_COMPOSITE_FLOOR 同时满足才启用软化"
        ),
    )

    # ── 紧急覆盖 ───────────────────────────────────────────────────────────────
    QUALITY_GATE_BYPASS_KEY: str = Field(
        default="",
        description="临时绕过密钥（极谨慎使用，仅 SUPERADMIN 权限）",
    )

    model_config = {
        "env_prefix": "SQ_",
        "extra": "ignore",
        "env_file": str(ENV_FILE) if ENV_FILE else ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# ── 运行时可变副本（由 API 热更新写入）────────────────────────────────────────────
_config_overrides: dict[str, Any] = {}
_base_config = SignalQualityConfig()


def get_signal_quality_config() -> SignalQualityConfig:
    """获取当前信号质量配置（含热更新覆盖）。"""
    if not _config_overrides:
        return _base_config
    # 将覆盖值合并进新的 config 实例
    base_dict = _base_config.model_dump()
    base_dict.update(_config_overrides)
    return SignalQualityConfig(**base_dict)


def apply_runtime_override(updates: dict[str, Any]) -> SignalQualityConfig:
    """热更新信号质量配置（无需重启服务）。"""
    _config_overrides.update(updates)
    new_cfg = get_signal_quality_config()
    logger.info(
        "[SignalQualityConfig] Runtime overrides applied: %s",
        list(updates.keys()),
    )
    return new_cfg


def reset_runtime_overrides() -> None:
    """清除所有热更新覆盖，恢复环境变量默认值。"""
    _config_overrides.clear()
    logger.info(
        "[SignalQualityConfig] Runtime overrides cleared, " "restored to env defaults."
    )


def get_regime_adjusted_config(regime: str) -> dict[str, Any]:
    """获取针对特定体制的自适应参数（合并到基础配置之上）。"""
    cfg = get_signal_quality_config()
    base = cfg.model_dump()
    overrides = _REGIME_OVERRIDES.get(regime, {})

    result = dict(base)
    if overrides:
        # 体制覆盖映射到 config 字段名
        if "conviction_threshold" in overrides:
            result["SIGNAL_CONFIDENCE_THRESHOLD"] = overrides["conviction_threshold"]
        if "resonance_min_dims" in overrides:
            result["SIGNAL_RESONANCE_MIN_DIMS"] = overrides["resonance_min_dims"]
        if "max_concurrent_positions" in overrides:
            result["MAX_CONCURRENT_POSITIONS"] = overrides["max_concurrent_positions"]
        result["long_allowed"] = overrides.get("long_allowed", True)
        result["short_allowed"] = overrides.get("short_allowed", True)
    else:
        result["long_allowed"] = True
        result["short_allowed"] = True

    return result
