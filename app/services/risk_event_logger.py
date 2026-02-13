from datetime import datetime
from typing import Optional, Dict


async def log_risk_event(
    session,
    account_id: str,
    event_type: str,
    level: str,
    message: str,
    symbol: Optional[str] = None,
    trade_mode_before: Optional[str] = None,
    trade_mode_after: Optional[str] = None,
    extra_json: Optional[Dict] = None,
):
    # Demo: print to stdout; in real system, persist to DB
    print(
        f"[{datetime.utcnow().isoformat()}] "
        f"{level} {event_type} account={account_id} symbol={symbol} "
        f"{message} extra={extra_json}"
    )
