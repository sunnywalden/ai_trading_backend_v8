from dataclasses import dataclass


@dataclass
class ShockPolicy:
    alert_drop_pct: float = 0.03
    alert_rally_pct: float = 0.04
    emergency_drop_pct: float = 0.06
    emergency_rally_pct: float = 0.08
    intrabar_shock_pct: float = 0.03
    window_minutes: int = 5
    emergency_reduce_fraction: float = 0.3
    emergency_max_new_risk_factor: float = 0.3
    recovery_minutes: int = 30
    recovery_risk_factor: float = 0.6


@dataclass
class EarningsShockPolicy:
    pre_days: int = 3
    post_days: int = 1
    vega_factor: float = 0.4
    gamma_factor: float = 0.5
    theta_factor: float = 0.6
    short_dte_factor: float = 0.3
    forbid_new_naked_shorts: bool = True
    require_spreads_for_shorts: bool = True
    min_dte_for_new_long: int = 7
    min_dte_for_new_short: int = 15
