"""Unit tests for V11.0.1 — ConvictionFrictionTracker

Tests:
  - record_rejection / record_pass 基本流程
  - FrictionState 数据结构和 to_dict()
  - can_use_soft_relief 逻辑（基于 soft_relief_used_count）
  - Redis 不可用时 graceful 降级
  - get_all_throttled_signals SCAN 路径
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.conviction_friction_tracker import (
    ConvictionFrictionTracker,
    FrictionState,
)


@pytest.fixture
def mock_redis():
    """模拟 Redis 客户端（Hash 操作）。"""
    redis = AsyncMock()
    # pipeline 是同步调用（非 await），必须用 MagicMock
    pipe = MagicMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.hset = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1])  # [new_count]
    redis.pipeline = MagicMock(return_value=pipe)  # 同步方法，不能用 AsyncMock
    redis.hgetall = AsyncMock(return_value={})
    redis.delete = AsyncMock(return_value=1)
    # scan cursor 返回 (0, []) 表示无更多结果
    redis.scan = AsyncMock(return_value=(0, []))
    return redis


@pytest.fixture
def tracker(mock_redis):
    return ConvictionFrictionTracker(redis_client=mock_redis)


class TestFrictionState:
    def test_to_dict_contains_expected_fields(self):
        state = FrictionState(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
            rejection_count=2,
            last_conviction=92.0,
            threshold_at_rejection=93,
            soft_relief_used_count=0,
            composite_score=97.0,
            resonance_bonus=82.0,
            soft_relief_eligible=True,
        )
        d = state.to_dict()
        assert d["symbol"] == "ORCL"
        assert d["direction"] == "LONG"
        assert d["soft_relief_eligible"] is True
        assert d["rejection_count"] == 2

    def test_soft_relief_eligible_false_by_default(self):
        state = FrictionState(
            symbol="X",
            direction="LONG",
            regime="NEUTRAL",
        )
        assert state.soft_relief_eligible is False


class TestRecordRejection:
    @pytest.mark.asyncio
    async def test_record_rejection_calls_pipeline(self, tracker, mock_redis):
        """record_rejection 应通过 Redis pipeline 写入 Hash 字段。"""
        count = await tracker.record_rejection(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
            conviction=92.0,
            threshold=93,
        )

        assert mock_redis.pipeline.called
        pipe = mock_redis.pipeline.return_value
        assert pipe.hincrby.called
        assert count == 1  # from mocked execute()[0]

    @pytest.mark.asyncio
    async def test_record_rejection_no_redis_graceful(self):
        """Redis 为 None 时返回 0，不抛异常。"""
        tracker_no_redis = ConvictionFrictionTracker(redis_client=None)
        count = await tracker_no_redis.record_rejection(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
            conviction=92.0,
            threshold=93,
        )
        assert count == 0


class TestRecordPass:
    @pytest.mark.asyncio
    async def test_record_pass_deletes_key(self, tracker, mock_redis):
        """record_pass 应 DELETE Redis 键以重置摩擦状态。"""
        await tracker.record_pass(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
        )
        assert mock_redis.delete.called

    @pytest.mark.asyncio
    async def test_record_pass_no_redis_graceful(self):
        tracker_no_redis = ConvictionFrictionTracker(redis_client=None)
        # Should not raise
        await tracker_no_redis.record_pass(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
        )


class TestCanUseSoftRelief:
    @pytest.mark.asyncio
    async def test_can_use_soft_relief_true_when_no_state(self, tracker, mock_redis):
        """无摩擦状态记录时，配额充足返回 True。"""
        mock_redis.hgetall.return_value = {}

        result = await tracker.can_use_soft_relief(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_can_use_soft_relief_false_when_quota_exhausted(
        self, tracker, mock_redis
    ):
        """soft_relief_used_count >= max_per_cycle 时返回 False。"""
        mock_redis.hgetall.return_value = {
            b"rejection_count": b"3",
            b"soft_relief_used_count": b"1",  # 已用完 max_per_cycle=1
            b"last_conviction": b"92.0",
            b"threshold_at_rejection": b"93",
        }

        result = await tracker.can_use_soft_relief(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
            max_per_cycle=1,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_can_use_soft_relief_true_when_quota_available(
        self, tracker, mock_redis
    ):
        mock_redis.hgetall.return_value = {
            b"rejection_count": b"2",
            b"soft_relief_used_count": b"0",
            b"last_conviction": b"91.5",
            b"threshold_at_rejection": b"93",
        }

        result = await tracker.can_use_soft_relief(
            symbol="ORCL",
            direction="LONG",
            regime="BULL_TREND",
            max_per_cycle=1,
        )
        assert result is True


class TestGetAllThrottledSignals:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_keys(self, tracker, mock_redis):
        """SCAN 返回空时，结果应为空列表。"""
        mock_redis.scan.return_value = (0, [])
        result = await tracker.get_all_throttled_signals(min_rejection_count=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_no_redis(self):
        tracker_no_redis = ConvictionFrictionTracker(redis_client=None)
        result = await tracker_no_redis.get_all_throttled_signals()
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_min_rejection_count(self, tracker, mock_redis):
        """min_rejection_count=3 时，count=1 的键应被过滤掉。"""
        mock_redis.scan.return_value = (
            0,
            [b"cv_friction:ORCL:LONG:BULL_TREND"],
        )
        # ORCL has rejection_count=1 — below min_rejection_count=3
        mock_redis.hgetall.return_value = {
            b"rejection_count": b"1",
            b"last_conviction": b"92.0",
            b"threshold_at_rejection": b"93",
            b"soft_relief_used_count": b"0",
        }

        result = await tracker.get_all_throttled_signals(min_rejection_count=3)
        assert result == []
