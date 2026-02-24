"""
市场交易时段工具 — US / HK 盘前·盘中·盘后判断

时段定义（UTC 换算）:
  美股 (ET = UTC-5 冬 / UTC-4 夏)
    盘前   04:00–09:30 ET
    正股   09:30–16:00 ET
    盘后   16:00–20:00 ET
    活跃区间: 04:00–20:00 ET（周一至周五）

  港股 (HKT = UTC+8)
    盘前   09:00–09:30 HKT
    上午盘 09:30–12:00 HKT
    午休   12:00–13:00 HKT（不扫描）
    下午盘 13:00–16:00 HKT
    活跃区间: 09:00–16:00 HKT（排除午休，周一至周五）
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_HKT = ZoneInfo("Asia/Hong_Kong")
_UTC = ZoneInfo("UTC")

# ────────── 美股时段边界（东部时间） ──────────
_US_ACTIVE_START = time(4, 0)    # 盘前开始
_US_ACTIVE_END = time(20, 0)     # 盘后结束

# ────────── 港股时段边界（香港时间） ──────────
_HK_ACTIVE_START = time(9, 0)    # 盘前开始
_HK_LUNCH_START = time(12, 0)    # 午休开始
_HK_LUNCH_END = time(13, 0)      # 午休结束
_HK_ACTIVE_END = time(16, 0)     # 收盘


def _now_utc() -> datetime:
    return datetime.now(tz=_UTC)


def is_us_market_active(now_utc: datetime | None = None) -> bool:
    """是否在美股活跃时段（盘前~盘后，周一至周五）"""
    now_et = (now_utc or _now_utc()).astimezone(_ET)
    if now_et.weekday() >= 5:   # 周六=5, 周日=6
        return False
    t = now_et.time()
    return _US_ACTIVE_START <= t < _US_ACTIVE_END


def is_hk_market_active(now_utc: datetime | None = None) -> bool:
    """是否在港股活跃时段（盘前~收盘，排除午休，周一至周五）"""
    now_hkt = (now_utc or _now_utc()).astimezone(_HKT)
    if now_hkt.weekday() >= 5:
        return False
    t = now_hkt.time()
    if t < _HK_ACTIVE_START or t >= _HK_ACTIVE_END:
        return False
    if _HK_LUNCH_START <= t < _HK_LUNCH_END:
        return False
    return True


def is_any_market_active(now_utc: datetime | None = None) -> bool:
    """是否有任意市场处于活跃时段"""
    ts = now_utc or _now_utc()
    return is_us_market_active(ts) or is_hk_market_active(ts)


def is_symbol_market_active(symbol: str, now_utc: datetime | None = None) -> bool:
    """根据标的代码判断对应市场是否活跃（港股以 .HK 后缀区分）"""
    ts = now_utc or _now_utc()
    if symbol.upper().endswith(".HK"):
        return is_hk_market_active(ts)
    return is_us_market_active(ts)


def market_status_summary(now_utc: datetime | None = None) -> dict:
    """返回当前各市场活跃状态摘要（用于日志/健康检查）"""
    ts = now_utc or _now_utc()
    return {
        "us_market_active": is_us_market_active(ts),
        "hk_market_active": is_hk_market_active(ts),
        "any_active": is_any_market_active(ts),
        "utc_time": ts.isoformat(),
        "et_time": ts.astimezone(_ET).strftime("%H:%M %Z"),
        "hkt_time": ts.astimezone(_HKT).strftime("%H:%M %Z"),
    }
