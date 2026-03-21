"""
src/handlers/get_recent_events.py
───────────────────────────────────
Lambda handler for GET /dashboard/recent-events

Returns the most recent N telemetry events formatted for
the Recent Device Events table widget:

[
  {
    "time":      "10:24:11",
    "patientId": "P001",
    "deviceId":  "D-P001-001AB",
    "eventType": "Data Sync",
    "status":    "successful"
  },
  ...
]

Query param:
  ?limit=20   Number of events to return (default 20, max 50)
"""

import logging
import os

from services.dynamodb_service import get_recent_events
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_DEFAULT_LIMIT = 20
_MAX_LIMIT      = 50


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/recent-events"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/recent-events")

    params = event.get("queryStringParameters") or {}
    try:
        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except (ValueError, TypeError):
        limit = _DEFAULT_LIMIT

    try:
        events = get_recent_events(limit=limit)

        return success({
            "events": events,
            "count":  len(events),
        })

    except Exception as exc:
        logger.error("GET /dashboard/recent-events failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve recent events.")
