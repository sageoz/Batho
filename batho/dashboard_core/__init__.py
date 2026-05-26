"""Batho Dashboard Core — Presentation layer with dumb proxy.

The dashboard is a pure presentation layer that:
1. Serves static dashboard assets (JS, CSS, HTML)
2. Proxies all API calls to the bridge_core HTTP server

It has ZERO business logic. All intelligence lives in bridge_core.
"""

from batho.dashboard_core.server import DashboardServer, serve_dashboard
from batho.dashboard_core.assets import find_dashboard_assets

__version__ = "2.0.0"

__all__ = [
    "DashboardServer",
    "serve_dashboard",
    "find_dashboard_assets",
]
