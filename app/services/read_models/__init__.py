# V11.1.1 Workbench read models
# Each module provides a single async function that composes data from multiple
# service queries into one response object — no business logic, no side effects.
from .admin_overview import get_admin_overview
from .dashboard_summary import get_dashboard_summary
from .executive_reports import (
    get_executive_performance_report,
    get_executive_risk_report,
    get_executive_summary,
)
from .order_book_workbench import get_order_book_workbench
from .research_home import get_research_home
from .system_monitor_workbench import get_system_monitor_workbench
from .trading_home import get_trading_home

__all__ = [
    "get_admin_overview",
    "get_dashboard_summary",
    "get_executive_performance_report",
    "get_executive_risk_report",
    "get_executive_summary",
    "get_order_book_workbench",
    "get_research_home",
    "get_system_monitor_workbench",
    "get_trading_home",
]
