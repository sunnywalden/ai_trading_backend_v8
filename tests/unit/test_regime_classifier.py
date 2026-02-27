"""V10.2-M1 单元测试：RegimeClassifier 核心逻辑

运行方式：
    cd ai_trading_backend_v8
    pytest tests/unit/test_regime_classifier.py -v

无需外部网络请求：所有 yfinance / DB 调用均通过 monkeypatch 模拟。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

# ── 被测模块 ──────────────────────────────────────────────────────────────────
from app.services.regime_classifier import RegimeScores
from app.models.market_regime import RegimeType


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: RegimeScores.classify()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeScoresClassify:
    """检验五维评分 → 体制分类映射逻辑。"""

    def test_bull_trend_high_trend_momentum(self):
        """强趋势 + 高动量 + 低波动 → BULL_TREND"""
        scores = RegimeScores(
            trend=85.0, vol=20.0, breadth=75.0, macro=70.0, momentum=80.0
        )
        regime, confidence = scores.classify()
        assert regime == RegimeType.BULL_TREND, f"Expected BULL_TREND, got {regime}"
        assert confidence > 0.5

    def test_bear_trend_low_trend_momentum(self):
        """弱趋势 + 低动量 + 高广度空头 → BEAR_TREND"""
        scores = RegimeScores(
            trend=15.0, vol=35.0, breadth=20.0, macro=25.0, momentum=10.0
        )
        regime, confidence = scores.classify()
        assert regime == RegimeType.BEAR_TREND, f"Expected BEAR_TREND, got {regime}"
        assert confidence > 0.3

    def test_high_vol_extreme_vix(self):
        """极端波动率 → HIGH_VOL 或 CRISIS"""
        scores = RegimeScores(
            trend=45.0, vol=95.0, breadth=40.0, macro=30.0, momentum=35.0
        )
        regime, confidence = scores.classify()
        assert regime in (RegimeType.HIGH_VOL, RegimeType.CRISIS), \
            f"Expected HIGH_VOL or CRISIS, got {regime}"

    def test_crisis_all_bearish(self):
        """全面悲观（趋势、广度、宏观均极低 + 极高波动）→ CRISIS"""
        scores = RegimeScores(
            trend=5.0, vol=98.0, breadth=5.0, macro=5.0, momentum=5.0
        )
        regime, confidence = scores.classify()
        assert regime == RegimeType.CRISIS, f"Expected CRISIS, got {regime}"
        assert confidence >= 0.6

    def test_mean_revert_moderate_all(self):
        """各维度处于中等、波动率偏高 → MEAN_REVERT"""
        scores = RegimeScores(
            trend=40.0, vol=65.0, breadth=50.0, macro=50.0, momentum=45.0
        )
        regime, _ = scores.classify()
        assert regime in (RegimeType.MEAN_REVERT, RegimeType.HIGH_VOL), \
            f"Expected MEAN_REVERT or HIGH_VOL, got {regime}"

    def test_range_bound_low_vol_neutral(self):
        """低波动 + 中等趋势 + 中等广度 → RANGE_BOUND"""
        scores = RegimeScores(
            trend=50.0, vol=18.0, breadth=55.0, macro=55.0, momentum=50.0
        )
        regime, _ = scores.classify()
        assert regime == RegimeType.RANGE_BOUND, \
            f"Expected RANGE_BOUND, got {regime}"

    def test_confidence_range(self):
        """置信度必须在 [0, 1] 范围内。"""
        for trend, vol, breadth, macro, momentum in [
            (90, 10, 90, 90, 90),
            (10, 90, 10, 10, 10),
            (50, 50, 50, 50, 50),
        ]:
            scores = RegimeScores(
                trend=float(trend), vol=float(vol),
                breadth=float(breadth), macro=float(macro),
                momentum=float(momentum),
            )
            _, confidence = scores.classify()
            assert 0.0 <= confidence <= 1.0, \
                f"Confidence out of range: {confidence}"

    def test_regime_type_is_valid_enum(self):
        """classify() 返回的 regime 必须是合法 RegimeType 枚举值。"""
        scores = RegimeScores(
            trend=60.0, vol=30.0, breadth=65.0, macro=60.0, momentum=55.0
        )
        regime, _ = scores.classify()
        assert regime in list(RegimeType), \
            f"{regime} is not a valid RegimeType"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: RegimeType enum values
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeType:
    """回归检测 RegimeType 枚举完整性。"""

    def test_all_six_regimes_exist(self):
        expected = {
            "BULL_TREND", "BEAR_TREND", "HIGH_VOL",
            "MEAN_REVERT", "RANGE_BOUND", "CRISIS",
        }
        actual = {r.value for r in RegimeType}
        assert actual == expected

    def test_regime_string_serialisable(self):
        """RegimeType 继承 str，可直接用于 JSON / DB 字段。"""
        for regime in RegimeType:
            assert isinstance(regime, str), \
                f"RegimeType.{regime.name} is not str-compatible"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: config REGIME_VAR_MULTIPLIERS 解析
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeVarMultiplierParsing:
    """检验 RiskGateService.set_regime_var_multiplier() 正确解析配置。"""

    def test_parse_and_apply_bull_trend(self):
        from app.services.risk_gate_service import RiskGateService
        svc = RiskGateService()
        svc.set_regime_var_multiplier("BULL_TREND")
        assert svc.get_regime_var_multiplier() > 1.0, \
            "BULL_TREND should have multiplier > 1.0"

    def test_parse_and_apply_crisis(self):
        from app.services.risk_gate_service import RiskGateService
        svc = RiskGateService()
        svc.set_regime_var_multiplier("CRISIS")
        assert svc.get_regime_var_multiplier() < 1.0, \
            "CRISIS should have multiplier < 1.0"

    def test_unknown_regime_uses_default_1(self):
        from app.services.risk_gate_service import RiskGateService
        svc = RiskGateService()
        svc.set_regime_var_multiplier("TOTALLY_UNKNOWN")
        assert svc.get_regime_var_multiplier() == 1.0, \
            "Unknown regime should default to 1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: EventBus 发布/订阅
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    """测试 AsyncIO EventBus 订阅/发布/取消订阅行为。"""

    @pytest.mark.asyncio
    async def test_publish_triggers_subscriber(self):
        from app.core.event_bus import EventBus, Topics

        bus = EventBus()
        received: list[dict] = []

        async def handler(payload: dict) -> None:
            received.append(payload)

        bus.subscribe(Topics.REGIME_CHANGED, handler)
        await bus.publish(Topics.REGIME_CHANGED, {"regime": "BULL_TREND"})

        assert len(received) == 1
        assert received[0]["regime"] == "BULL_TREND"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        from app.core.event_bus import EventBus, Topics

        bus = EventBus()
        received: list[dict] = []

        async def handler(payload: dict) -> None:
            received.append(payload)

        bus.subscribe(Topics.REGIME_CHANGED, handler)
        bus.unsubscribe(Topics.REGIME_CHANGED, handler)
        await bus.publish(Topics.REGIME_CHANGED, {"regime": "CRISIS"})

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_others(self):
        """一个 handler 抛出异常不影响同 topic 其他 handler。"""
        from app.core.event_bus import EventBus, Topics

        bus = EventBus()
        good_received: list[dict] = []

        async def bad_handler(payload: dict) -> None:
            raise RuntimeError("intentional error")

        async def good_handler(payload: dict) -> None:
            good_received.append(payload)

        bus.subscribe(Topics.REGIME_CHANGED, bad_handler)
        bus.subscribe(Topics.REGIME_CHANGED, good_handler)
        await bus.publish(Topics.REGIME_CHANGED, {"regime": "HIGH_VOL"})

        # good_handler 必须收到消息
        assert len(good_received) == 1
