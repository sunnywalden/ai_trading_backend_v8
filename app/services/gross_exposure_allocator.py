from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import settings


@dataclass
class GrossExposureAllocation:
    enabled: bool
    reason: str
    regime: str
    target_config_source: str
    max_config_source: str
    current_gross_exposure_pct: float
    current_net_exposure_pct: float
    current_symbol_exposure_pct: float
    target_gross_exposure_pct: float
    max_gross_exposure_pct: float
    remaining_target_pct: float
    remaining_cap_pct: float
    max_additional_symbol_pct: float
    base_position_pct: float
    allocated_position_pct: float
    target_qty: float
    max_qty_allowed: float
    boost_applied: bool
    capped: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, float):
                payload[key] = round(value, 6)
        return payload


class GrossExposureAllocator:
    """目标总敞口分配器。

    设计目标：
    - 当当前 gross exposure 低于目标值时，为 ENTRY/ADD 信号自动抬升基础仓位，
      让系统向目标杠杆收敛；
    - 当当前 gross exposure 或单标的仓位接近上限时，对开仓信号进行裁剪；
    - 不改动 EXIT/REDUCE 路径，也不替代 RiskGate，只在下单数量生成前做预分配。
    """

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _resolve_position_price(cls, position: Any) -> float:
        if not isinstance(position, dict):
            return 0.0
        for key in ("current_price", "market_price", "price", "avg_cost"):
            value = cls._safe_float(position.get(key), 0.0)
            if value > 0:
                return value
        return 0.0

    @classmethod
    def _portfolio_exposure_snapshot(
        cls,
        positions: dict[str, Any],
        equity: float,
    ) -> tuple[float, float]:
        if equity <= 0:
            return 0.0, 0.0

        gross_notional = 0.0
        net_notional = 0.0
        for pos in positions.values():
            if not isinstance(pos, dict):
                continue
            qty = cls._safe_float(pos.get("qty"), 0.0)
            price = cls._resolve_position_price(pos)
            if qty == 0 or price <= 0:
                continue
            notional = qty * price
            gross_notional += abs(notional)
            net_notional += notional

        return gross_notional / equity, net_notional / equity

    @classmethod
    def _parse_regime_map(cls, raw: Any) -> dict[str, float]:
        mapping: dict[str, float] = {}
        text = str(raw or "").strip()
        if not text:
            return mapping
        for item in text.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            regime, value = item.split(":", 1)
            regime = regime.strip().upper()
            if not regime:
                continue
            parsed = cls._safe_float(value.strip(), float("nan"))
            if parsed == parsed:
                mapping[regime] = parsed
        return mapping

    def resolve_regime_targets(self, regime: str | None) -> dict[str, Any]:
        regime_name = str(regime or "SIDEWAYS").upper()
        base_target = max(
            0.0,
            self._safe_float(getattr(settings, "TARGET_GROSS_EXPOSURE_PCT", 1.5), 1.5),
        )
        base_max = max(
            base_target,
            self._safe_float(getattr(settings, "MAX_GROSS_EXPOSURE_PCT", 2.0), 2.0),
        )
        target_map = self._parse_regime_map(
            getattr(settings, "GROSS_EXPOSURE_TARGET_BY_REGIME", "")
        )
        max_map = self._parse_regime_map(
            getattr(settings, "MAX_GROSS_EXPOSURE_BY_REGIME", "")
        )

        target_value = target_map.get(regime_name, base_target)
        max_value = max(max_map.get(regime_name, base_max), target_value)
        return {
            "regime": regime_name,
            "target_gross_exposure_pct": target_value,
            "max_gross_exposure_pct": max_value,
            "target_config_source": (
                f"regime:{regime_name}" if regime_name in target_map else "base"
            ),
            "max_config_source": (
                f"regime:{regime_name}" if regime_name in max_map else "base"
            ),
        }

    def build_runtime_summary(
        self,
        *,
        positions: dict[str, Any],
        equity: float,
        regime: str | None,
    ) -> dict[str, Any]:
        regime_targets = self.resolve_regime_targets(regime)
        current_gross_pct, current_net_pct = self._portfolio_exposure_snapshot(
            positions,
            equity,
        )
        target_gross_pct = float(regime_targets["target_gross_exposure_pct"])
        max_gross_pct = float(regime_targets["max_gross_exposure_pct"])
        return {
            **regime_targets,
            "current_gross_exposure_pct": round(current_gross_pct, 6),
            "current_net_exposure_pct": round(current_net_pct, 6),
            "distance_to_target_gross_exposure_pct": round(
                target_gross_pct - current_gross_pct,
                6,
            ),
            "remaining_to_max_gross_exposure_pct": round(
                max_gross_pct - current_gross_pct,
                6,
            ),
        }

    def allocate_entry(
        self,
        *,
        symbol: str,
        price: float,
        equity: float,
        current_positions: dict[str, Any],
        base_position_pct: float,
        explicit_abs_qty: bool = False,
        regime: str | None = None,
    ) -> GrossExposureAllocation:
        base_pct = max(0.0, self._safe_float(base_position_pct, 0.0))
        regime_targets = self.resolve_regime_targets(regime)
        regime_name = str(regime_targets["regime"])
        target_gross_pct = float(regime_targets["target_gross_exposure_pct"])
        max_gross_pct = float(regime_targets["max_gross_exposure_pct"])
        target_config_source = str(regime_targets["target_config_source"])
        max_config_source = str(regime_targets["max_config_source"])
        slice_count = max(
            1,
            int(self._safe_float(getattr(settings, "GROSS_EXPOSURE_ENTRY_SLICE_COUNT", 4), 4)),
        )
        allocator_enabled = bool(
            getattr(settings, "GROSS_EXPOSURE_ALLOCATOR_ENABLED", True)
        )

        current_gross_pct, current_net_pct = self._portfolio_exposure_snapshot(
            current_positions,
            equity,
        )
        current_symbol = current_positions.get(symbol, {})
        current_symbol_qty = self._safe_float(
            current_symbol.get("qty") if isinstance(current_symbol, dict) else 0.0,
            0.0,
        )
        current_symbol_price = self._resolve_position_price(current_symbol) or max(
            price,
            0.0,
        )
        current_symbol_pct = (
            abs(current_symbol_qty * current_symbol_price) / equity
            if equity > 0 and current_symbol_price > 0
            else 0.0
        )

        max_single_pct = max(
            0.0,
            self._safe_float(getattr(settings, "MAX_SINGLE_POSITION_PCT", 0.25), 0.25),
        )
        max_additional_symbol_pct = max(0.0, max_single_pct - current_symbol_pct)
        remaining_target_pct = max(0.0, target_gross_pct - current_gross_pct)
        remaining_cap_pct = max(0.0, max_gross_pct - current_gross_pct)

        if not allocator_enabled:
            allocated_pct = min(base_pct, max_additional_symbol_pct, remaining_cap_pct)
            max_qty = (
                (min(max_additional_symbol_pct, remaining_cap_pct) * equity) / price
                if price > 0 and equity > 0
                else 0.0
            )
            return GrossExposureAllocation(
                enabled=False,
                reason="allocator-disabled",
                regime=regime_name,
                target_config_source=target_config_source,
                max_config_source=max_config_source,
                current_gross_exposure_pct=current_gross_pct,
                current_net_exposure_pct=current_net_pct,
                current_symbol_exposure_pct=current_symbol_pct,
                target_gross_exposure_pct=target_gross_pct,
                max_gross_exposure_pct=max_gross_pct,
                remaining_target_pct=remaining_target_pct,
                remaining_cap_pct=remaining_cap_pct,
                max_additional_symbol_pct=max_additional_symbol_pct,
                base_position_pct=base_pct,
                allocated_position_pct=allocated_pct,
                target_qty=max_qty if allocated_pct > 0 and base_pct > 0 else 0.0,
                max_qty_allowed=max_qty,
                boost_applied=False,
                capped=allocated_pct < base_pct,
            )

        if equity <= 0 or price <= 0:
            return GrossExposureAllocation(
                enabled=False,
                reason="missing-equity-or-price",
                regime=regime_name,
                target_config_source=target_config_source,
                max_config_source=max_config_source,
                current_gross_exposure_pct=current_gross_pct,
                current_net_exposure_pct=current_net_pct,
                current_symbol_exposure_pct=current_symbol_pct,
                target_gross_exposure_pct=target_gross_pct,
                max_gross_exposure_pct=max_gross_pct,
                remaining_target_pct=remaining_target_pct,
                remaining_cap_pct=remaining_cap_pct,
                max_additional_symbol_pct=max_additional_symbol_pct,
                base_position_pct=base_pct,
                allocated_position_pct=0.0,
                target_qty=0.0,
                max_qty_allowed=0.0,
                boost_applied=False,
                capped=False,
            )

        if remaining_cap_pct <= 0 or max_additional_symbol_pct <= 0:
            return GrossExposureAllocation(
                enabled=True,
                reason="no-headroom",
                regime=regime_name,
                target_config_source=target_config_source,
                max_config_source=max_config_source,
                current_gross_exposure_pct=current_gross_pct,
                current_net_exposure_pct=current_net_pct,
                current_symbol_exposure_pct=current_symbol_pct,
                target_gross_exposure_pct=target_gross_pct,
                max_gross_exposure_pct=max_gross_pct,
                remaining_target_pct=remaining_target_pct,
                remaining_cap_pct=remaining_cap_pct,
                max_additional_symbol_pct=max_additional_symbol_pct,
                base_position_pct=base_pct,
                allocated_position_pct=0.0,
                target_qty=0.0,
                max_qty_allowed=0.0,
                boost_applied=False,
                capped=base_pct > 0,
            )

        desired_pct = base_pct
        boost_applied = False
        reason = "base-size"

        if not explicit_abs_qty and current_gross_pct < target_gross_pct and remaining_target_pct > 0:
            slice_pct = remaining_target_pct / slice_count
            desired_pct = max(base_pct, slice_pct)
            boost_applied = desired_pct > base_pct
            reason = "boost-to-target" if boost_applied else reason
        elif explicit_abs_qty:
            reason = "explicit-abs-shares"

        allowed_pct = min(desired_pct, max_additional_symbol_pct, remaining_cap_pct)
        capped = allowed_pct + 1e-9 < desired_pct
        target_qty = (allowed_pct * equity) / price if allowed_pct > 0 else 0.0
        max_qty_allowed = (
            (min(max_additional_symbol_pct, remaining_cap_pct) * equity) / price
            if price > 0
            else 0.0
        )

        return GrossExposureAllocation(
            enabled=True,
            reason=reason,
            regime=regime_name,
            target_config_source=target_config_source,
            max_config_source=max_config_source,
            current_gross_exposure_pct=current_gross_pct,
            current_net_exposure_pct=current_net_pct,
            current_symbol_exposure_pct=current_symbol_pct,
            target_gross_exposure_pct=target_gross_pct,
            max_gross_exposure_pct=max_gross_pct,
            remaining_target_pct=remaining_target_pct,
            remaining_cap_pct=remaining_cap_pct,
            max_additional_symbol_pct=max_additional_symbol_pct,
            base_position_pct=base_pct,
            allocated_position_pct=allowed_pct,
            target_qty=target_qty,
            max_qty_allowed=max_qty_allowed,
            boost_applied=boost_applied,
            capped=capped,
        )


gross_exposure_allocator = GrossExposureAllocator()