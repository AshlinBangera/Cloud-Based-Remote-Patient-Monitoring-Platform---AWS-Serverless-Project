"""
src/handlers/get_sync_frequency.py
────────────────────────────────────
Lambda handler for GET /dashboard/sync-frequency

Returns hourly sync event counts for the last 24 hours,
formatted for the Device Sync Frequency line chart:

{
  "labels": ["00:00", "01:00", ..., "23:00"],
  "values": [3, 5, 2, 4, ...]
}
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from services.dynamodb_service import get_aggregates
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/sync-frequency"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/sync-frequency")

    try:
        # Build a full 24-hour skeleton with zero counts
        now = datetime.now(timezone.utc)
        hours: dict[str, int] = {}
        for i in range(24):
            hour_dt    = now - timedelta(hours=23 - i)
            hour_label = f"{hour_dt.hour:02d}:00"
            hours[hour_label] = 0

        # Overlay real counts from DashboardAggregates
        aggregates = get_aggregates("sync-frequency", limit=48)
        for agg in aggregates:
            data  = agg.get("data", {})
            label = data.get("label", "")
            count = int(data.get("count", 0))
            if label in hours:
                hours[label] += count

        labels = list(hours.keys())
        values = list(hours.values())

        return success({
            "labels": labels,
            "values": values,
        })

    except Exception as exc:
        logger.error("GET /dashboard/sync-frequency failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve sync frequency data.")
