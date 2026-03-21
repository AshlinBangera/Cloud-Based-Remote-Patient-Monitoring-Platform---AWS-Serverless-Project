"""
src/utils/time_buckets.py
─────────────────────────
Utilities for converting ISO 8601 timestamps into time buckets
used by the heatmap and sync-frequency aggregations.
"""

from datetime import datetime, timezone
from typing import Literal

# The 7 three-hour buckets used by the cardiac event heatmap
HEATMAP_BUCKETS = ["00", "03", "06", "09", "12", "15", "18"]

# Days of the week ordered Monday–Sunday (matches the dashboard)
DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_iso(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a UTC datetime."""
    ts = timestamp.rstrip("Z")
    if "+" in ts or (ts.count("-") > 2):
        dt = datetime.fromisoformat(timestamp)
        return dt.astimezone(timezone.utc)
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def get_heatmap_bucket(timestamp: str) -> str:
    """
    Map a timestamp to its 3-hour bucket label (e.g. '06' for 07:45).

    Returns one of: '00', '03', '06', '09', '12', '15', '18'
    Hours 21–23 are folded into '18'.
    """
    dt = parse_iso(timestamp)
    hour = dt.hour
    bucket_hour = (hour // 3) * 3
    bucket_hour = min(bucket_hour, 18)
    return f"{bucket_hour:02d}"


def get_day_of_week(timestamp: str) -> str:
    """Return the abbreviated day name for a timestamp (e.g. 'Mon')."""
    dt = parse_iso(timestamp)
    return DAYS_OF_WEEK[dt.weekday()]


def get_hour_label(timestamp: str) -> str:
    """Return 'HH:00' label for grouping sync-frequency by hour."""
    dt = parse_iso(timestamp)
    return f"{dt.hour:02d}:00"


def get_period_key(metric_type: str, timestamp: str) -> str:
    """
    Build a DashboardAggregates sort key from metric type + timestamp.

    Format: 'sync-frequency#2026-03-20T14' (hourly resolution)
    """
    dt = parse_iso(timestamp)
    hour_str = dt.strftime("%Y-%m-%dT%H")
    return f"{metric_type}#{hour_str}"


def now_utc_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
