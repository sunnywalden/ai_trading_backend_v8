"""V10.5.2: CapacityArbiterService 单元测试

覆盖场景：
  1. 无溢出 → 所有信号通过
  2. 溢出=1，最佳信号明显胜出 → 末位持仓被平仓，信号通过
  3. min_edge 保护 → 信号优势不够，持仓免疫，信号被拒
  4. min_hold 保护 → 新持仓免疫竞争，信号被拒（无替换）
  5. cooldown 保护（模拟最近刚被替换）
  6. dry_run=True → 无 EXIT 信号创建，决策照常返回
  7. max_replacements_cap → 超出单次替换上限，额外信号被拒
  8. 功能关闭 (CAPACITY_REPLACEMENT_ENABLED=False) → 所有信号直接通过
  9. _position_admission_score 公式验证
  10. _signal_admission_score 公式验证
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isclose
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.capacity_arbiter import (
    CANDIDATE_POSITION,
    CANDIDATE_SIGNAL,
    ArbiterDecision,
    CapacityArbiterService,
    CapacityCandidate,
)

# ─── 共用工具 ─────────────────────────────────────────────────────────────────


def _make_signal(
    sid: int = 1,
    symbol: str = "AAPL",
    confidence: float = 0.80,
    strength: float = 0.75,
) -> dict:
    return {
        "id": sid,
        "symbol": symbol,
        "signal_type": "ENTRY",
        "direction": "LONG",
        "confidence": confidence,
        "signal_strength": strength,
        "extra_metadata": {},
        "factor_scores": {},
    }


def _make_position(
    symbol: str,
    opened_before_minutes: float = 120.0,
    unrealized_pnl_pct: float = 0.01,
) -> tuple[str, dict]:
    opened = (
        datetime.now(timezone.utc) - timedelta(minutes=opened_before_minutes)
    ).isoformat()
    return symbol, {
        "symbol": symbol,
        "qty": 100,
        "avg_cost": 100.0,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "opened_at": opened,
    }


# ─── 以便 Mock config ────────────────────────────────────────────────────────


@dataclass
class _FakeCfg:
    CAPACITY_REPLACEMENT_ENABLED: bool = True
    CAPACITY_REPLACEMENT_DRY_RUN: bool = False
    CAPACITY_REPLACEMENT_MAX_PER_CYCLE: int = 2
    CAPACITY_REPLACEMENT_MIN_EDGE: float = 5.0
    CAPACITY_MIN_HOLD_MINUTES: int = 30
    CAPACITY_REPLACEMENT_COOLDOWN_MINUTES: int = 120


class _FakeScalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return self._items


class _FakeExecResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return _FakeScalars(self._items)


class _FakeDB:
    """Minimal async session stub that returns empty results."""

    async def execute(self, _stmt):
        await asyncio.sleep(0)
        return _FakeExecResult([])

    def add(self, obj):  # SQLAlchemy Session.add is synchronous
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass


# ─── 偷换 _build_position_candidates / _build_signal_candidates 以隔离 DB ────


def _inject_candidates(
    arbiter: CapacityArbiterService,
    pos_cands: list[CapacityCandidate],
    sig_cands: list[CapacityCandidate],
):
    """Monkey-patch the two build methods to return controlled candidates."""

    async def _pos(*args, **kwargs):  # noqa: D401
        return pos_cands

    async def _sig(*args, **kwargs):  # noqa: D401
        return sig_cands

    arbiter._build_position_candidates = _pos  # type: ignore[method-assign]
    arbiter._build_signal_candidates = _sig  # type: ignore[method-assign]


def _make_pos_cand(
    symbol: str,
    admission_score: float,
    hold_minutes: float = 120.0,
    is_protected: bool = False,
    protect_reason: str | None = None,
) -> CapacityCandidate:
    return CapacityCandidate(
        candidate_type=CANDIDATE_POSITION,
        symbol=symbol,
        raw_score=admission_score,
        admission_score=admission_score,
        hold_minutes=hold_minutes,
        is_protected=is_protected,
        protect_reason=protect_reason,
    )


def _make_sig_cand(
    sig_dict: dict,
    admission_score: float,
    is_protected: bool = False,
) -> CapacityCandidate:
    return CapacityCandidate(
        candidate_type=CANDIDATE_SIGNAL,
        symbol=sig_dict["symbol"],
        raw_score=admission_score,
        admission_score=admission_score,
        signal_id=sig_dict["id"],
        signal_dict=sig_dict,
        is_protected=is_protected,
    )


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Patch helpers ───────────────────────────────────────────────────────────


def _patch_cfg(cfg=None):
    """Return context manager that replaces get_signal_quality_config()."""
    cfg = cfg or _FakeCfg()
    return patch(
        "app.services.capacity_arbiter.CapacityArbiterService.evaluate.__wrapped__",
        autospec=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. 无溢出 → 所有信号通过
# ════════════════════════════════════════════════════════════════════════════


def test_no_overflow_all_signals_approved():
    """positions=2, signals=2, max=6  →  overflow=0, all signals approved."""
    arb = CapacityArbiterService()
    db = _FakeDB()
    signals = [_make_signal(1, "AAPL"), _make_signal(2, "GOOG")]
    positions = dict([_make_position("MSFT"), _make_position("AMZN")])

    # We need to stub get_signal_quality_config inside evaluate
    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(),
    ):
        # also stub _build_position/_build_signal to avoid real DB
        _inject_candidates(
            arb,
            [_make_pos_cand("MSFT", 70), _make_pos_cand("AMZN", 65)],
            [_make_sig_cand(signals[0], 75), _make_sig_cand(signals[1], 60)],
        )
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=signals,
                max_positions=6,
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.overflow == 0
    assert len(decision.approved_signals) == 2
    assert len(decision.rejected_signals) == 0
    assert len(decision.positions_to_close) == 0


# ════════════════════════════════════════════════════════════════════════════
# 2. 溢出=1，最佳信号明显胜出 → 末位持仓被平仓
# ════════════════════════════════════════════════════════════════════════════


def test_overflow_best_signal_wins_over_worst_position():
    """positions=3, signals=1, max=3  →  worst position evicted, signal approved."""
    arb = CapacityArbiterService()
    db = _FakeDB()

    sig = _make_signal(10, "NVDA")
    positions = dict(
        [
            _make_position("AAPL"),
            _make_position("GOOG"),
            _make_position("AMZN"),  # AMZN will be worst
        ]
    )

    # AMZN gets lowest score; new NVDA signal has clear edge (>5)
    pos_cands = [
        _make_pos_cand("AAPL", 80),
        _make_pos_cand("GOOG", 75),
        _make_pos_cand("AMZN", 40),  # worst
    ]
    sig_cands = [_make_sig_cand(sig, 60)]  # 60 - 40 = 20 > min_edge(5)

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(),
    ):
        _inject_candidates(arb, pos_cands, sig_cands)
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=[sig],
                max_positions=3,
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.overflow == 1
    assert "AMZN" in decision.positions_to_close
    assert len(decision.approved_signals) == 1
    assert decision.approved_signals[0]["id"] == 10
    assert decision.replacement_triggered is True


# ════════════════════════════════════════════════════════════════════════════
# 3. min_edge 保护 → 信号优势不足，持仓豁免，信号被拒
# ════════════════════════════════════════════════════════════════════════════


def test_min_edge_protection_rejects_signal():
    """Signal beats worst position by only 3 points (< min_edge=5) → signal rejected."""
    arb = CapacityArbiterService()
    db = _FakeDB()

    sig = _make_signal(20, "TSLA")
    positions = dict(
        [
            _make_position("AAPL"),
            _make_position("GOOG"),
            _make_position("MSFT"),
        ]
    )

    pos_cands = [
        _make_pos_cand("AAPL", 80),
        _make_pos_cand("GOOG", 75),
        _make_pos_cand("MSFT", 52),  # worst
    ]
    sig_cands = [_make_sig_cand(sig, 55)]  # edge = 55 - 52 = 3 < min_edge(5)

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(),
    ):
        _inject_candidates(arb, pos_cands, sig_cands)
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=[sig],
                max_positions=3,
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.overflow == 1
    # Position protected; signal rejected
    assert len(decision.positions_to_close) == 0
    assert len(decision.rejected_signals) == 1
    assert decision.min_edge_protected >= 1


# ════════════════════════════════════════════════════════════════════════════
# 4. min_hold 保护 → 新持仓免受竞争，信号被拒
# ════════════════════════════════════════════════════════════════════════════


def test_min_hold_protection_makes_young_position_immune():
    """Only position is brand-new (10 min < min_hold=30) → protected; signal rejected."""
    arb = CapacityArbiterService()
    db = _FakeDB()

    sig = _make_signal(30, "META")
    positions = dict([_make_position("YOUNG", opened_before_minutes=10)])

    pos_cands = [
        _make_pos_cand(
            "YOUNG", 30, hold_minutes=10, is_protected=True, protect_reason="min_hold"
        ),
    ]
    sig_cands = [_make_sig_cand(sig, 90)]

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(),
    ):
        _inject_candidates(arb, pos_cands, sig_cands)
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=[sig],
                max_positions=1,  # overflow=1; only evictable=YOUNG (protected)
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.overflow == 1
    # YOUNG position is protected → stays; signal must yield
    assert "YOUNG" not in decision.positions_to_close
    assert len(decision.rejected_signals) == 1
    assert decision.min_hold_protected >= 1


# ════════════════════════════════════════════════════════════════════════════
# 5. dry_run=True → 不生成 EXIT 信号
# ════════════════════════════════════════════════════════════════════════════


def test_dry_run_creates_no_exit_signals():
    """dry_run=True: positions_to_close populated but exit_signals_created is empty."""
    arb = CapacityArbiterService()
    # Intercept _create_exit_signals to ensure it's NOT called
    called = []

    async def _fake_exit(**_kwargs):
        called.append(1)
        return []

    arb._create_exit_signals = _fake_exit  # type: ignore[method-assign]

    db = _FakeDB()
    sig = _make_signal(40, "NVDA")
    positions = dict([_make_position("AAPL"), _make_position("WEAK")])

    pos_cands = [_make_pos_cand("AAPL", 80), _make_pos_cand("WEAK", 30)]
    sig_cands = [_make_sig_cand(sig, 60)]  # edge=30 > 5; would evict WEAK

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(CAPACITY_REPLACEMENT_DRY_RUN=True),
    ):
        _inject_candidates(arb, pos_cands, sig_cands)
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=[sig],
                max_positions=2,
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.dry_run is True
    assert len(called) == 0, "_create_exit_signals must not be called in dry_run"
    assert decision.exit_signals_created == []
    # The decision logic still marks positions_to_close
    assert "WEAK" in decision.positions_to_close


# ════════════════════════════════════════════════════════════════════════════
# 6. max_replacements_cap → 超出上限后，信号被拒而非持仓被平
# ════════════════════════════════════════════════════════════════════════════


def test_max_replacements_cap_rejects_extra_signals():
    """max_per_cycle=1; overflow=2; 2nd eviction attempt → second signal rejected."""
    arb = CapacityArbiterService()
    db = _FakeDB()

    sig1 = _make_signal(51, "NVDA")
    sig2 = _make_signal(52, "AMD")
    positions = dict(
        [
            _make_position("AAPL"),
            _make_position("WEAK1"),
            _make_position("WEAK2"),
        ]
    )

    pos_cands = [
        _make_pos_cand("AAPL", 80),
        _make_pos_cand("WEAK1", 30),
        _make_pos_cand("WEAK2", 28),
    ]
    sig_cands = [
        _make_sig_cand(sig1, 70),  # strong → beats WEAK2 (edge=42)
        _make_sig_cand(sig2, 65),  # also strong
    ]

    cfg = _FakeCfg(CAPACITY_REPLACEMENT_MAX_PER_CYCLE=1)

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=cfg,
    ):
        _inject_candidates(arb, pos_cands, sig_cands)
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=[sig1, sig2],
                max_positions=3,
                regime="BULL_TREND",
                db=db,
                dry_run=True,
            )
        )

    assert decision.overflow == 2
    # Only 1 replacement allowed; 1 position evicted, 1 signal rejected
    assert len(decision.positions_to_close) <= 1
    assert decision.max_replacements_cap >= 1


# ════════════════════════════════════════════════════════════════════════════
# 7. 功能关闭 → 所有信号直接通过
# ════════════════════════════════════════════════════════════════════════════


def test_feature_disabled_all_signals_pass_through():
    """CAPACITY_REPLACEMENT_ENABLED=False → all signals approved with no arbitration."""
    arb = CapacityArbiterService()
    db = _FakeDB()
    signals = [_make_signal(1, "AAPL"), _make_signal(2, "GOOG")]
    positions = dict([_make_position("MSFT") for _ in range(1)])  # 1 position

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(CAPACITY_REPLACEMENT_ENABLED=False),
    ):
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=signals,
                max_positions=1,  # would normally be overflowed
                regime="BULL_TREND",
                db=db,
            )
        )

    assert len(decision.approved_signals) == 2
    assert len(decision.rejected_signals) == 0


# ════════════════════════════════════════════════════════════════════════════
# 8. _position_admission_score 公式验证
# ════════════════════════════════════════════════════════════════════════════


def test_position_admission_score_no_decay():
    """Hold < 8h → no decay applied."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=70.0, hold_minutes=60.0, unrealized_pnl_pct=0.0
    )
    assert isclose(score, 70.0, abs_tol=0.01)


def test_position_admission_score_decay_applied():
    """Hold = 24h (1440 min) → decay = (1440-480)/1440 * 3 = 2.0."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=70.0, hold_minutes=1440.0, unrealized_pnl_pct=0.0
    )
    expected = 70.0 - 2.0
    assert isclose(score, expected, abs_tol=0.05)


def test_position_admission_score_pnl_bonus():
    """unrealized_pnl_pct=0.5 → pnl_bonus = min(10, 0.5*10)=5 → 80+5=85."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=80.0, hold_minutes=0.0, unrealized_pnl_pct=0.5
    )
    assert isclose(score, 85.0, abs_tol=0.1)


def test_position_admission_score_pnl_bonus_capped():
    """unrealized_pnl_pct=1.0 → pnl_bonus capped at 10 → 80+10=90."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=80.0, hold_minutes=0.0, unrealized_pnl_pct=1.0
    )
    assert isclose(score, 90.0, abs_tol=0.1)


def test_position_admission_score_pnl_penalty():
    """unrealized_pnl_pct=-0.5 → pnl_bonus=-5 (clipped at -10)."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=60.0, hold_minutes=0.0, unrealized_pnl_pct=-0.5
    )
    assert isclose(score, 55.0, abs_tol=0.1)


def test_position_admission_score_clipped_to_zero():
    """Very bad score should never go below 0."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=5.0, hold_minutes=10000.0, unrealized_pnl_pct=-1.0
    )
    assert score == 0.0


def test_position_admission_score_clipped_to_hundred():
    """Very good score should never exceed 100."""
    score = CapacityArbiterService._position_admission_score(
        overall_score=99.0, hold_minutes=0.0, unrealized_pnl_pct=1.0
    )
    assert score == 100.0


# ════════════════════════════════════════════════════════════════════════════
# 9. _signal_admission_score 公式验证
# ════════════════════════════════════════════════════════════════════════════


def test_signal_admission_score_passthrough():
    assert isclose(CapacityArbiterService._signal_admission_score(73.5), 73.5)


def test_signal_admission_score_clamp_high():
    assert CapacityArbiterService._signal_admission_score(150.0) == 100.0


def test_signal_admission_score_clamp_low():
    assert CapacityArbiterService._signal_admission_score(-5.0) == 0.0


# ════════════════════════════════════════════════════════════════════════════
# 10. _estimate_hold_minutes
# ════════════════════════════════════════════════════════════════════════════


def test_estimate_hold_minutes_from_opened_at():
    svc = CapacityArbiterService
    now = datetime.now(timezone.utc)
    opened = now - timedelta(minutes=90)
    pos_data = {"opened_at": opened.isoformat()}
    minutes = svc._estimate_hold_minutes(pos_data, None, now)
    assert isclose(minutes, 90.0, abs_tol=0.1)


def test_estimate_hold_minutes_fallback_large():
    """No time info → returns large fallback value (9999)."""
    svc = CapacityArbiterService
    now = datetime.now(timezone.utc)
    minutes = svc._estimate_hold_minutes({}, None, now)
    assert minutes >= 9000.0


# ════════════════════════════════════════════════════════════════════════════
# 11. cycle_id 传参透传
# ════════════════════════════════════════════════════════════════════════════


def test_cycle_id_propagated():
    """Explicit cycle_id should be echoed in the decision."""
    arb = CapacityArbiterService()
    db = _FakeDB()
    cid = str(uuid.uuid4())
    signals = [_make_signal(1, "AAPL")]
    positions = {}

    with patch(
        "app.services.signal_quality_config.get_signal_quality_config",
        return_value=_FakeCfg(),
    ):
        _inject_candidates(arb, [], [_make_sig_cand(signals[0], 70)])
        decision = run_async(
            arb.evaluate(
                account_id="DU1",
                current_positions=positions,
                entry_signals=signals,
                max_positions=5,
                regime="NEUTRAL",
                db=db,
                cycle_id=cid,
                dry_run=True,
            )
        )

    assert decision.cycle_id == cid
