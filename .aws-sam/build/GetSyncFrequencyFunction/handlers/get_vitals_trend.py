"""
src/handlers/get_vitals_trend.py
──────────────────────────────────
Lambda handler for GET /dashboard/vitals-trend

Returns rolling heart rate and blood pressure time series
for the Patient Vitals Trending dual-line chart:

{
  "labels":       ["T1", "T2", ...],
  "heartRate":    [84, 88, 92, ...],
  "bloodPressure": [110, 108, 112, ...]
}

Query param:
  ?limit=20   Number of data points to return (default 20, max 100)
"""

import logging
import os

from services.dynamodb_service import get_aggregates
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_DEFAULT_LIMIT = 20
_MAX_LIMIT      = 100


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/vitals-trend"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/vitals-trend")

    # Parse optional limit query param
    params = event.get("queryStringParameters") or {}
    try:
        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except (ValueError, TypeError):
        limit = _DEFAULT_LIMIT

    try:
        aggregates = get_aggregates("vitals-trend", limit=limit)

        # Aggregates come back newest-first; reverse for chronological display
        aggregates = list(reversed(aggregates))

        labels = []
        hr_values = []
        bp_values = []

        for i, agg in enumerate(aggregates):
            data = agg.get("data", {})
            labels.append(data.get("label", f"T{i + 1}"))
            hr_values.append(float(data.get("heartRate",     75.0)))
            bp_values.append(float(data.get("bloodPressure", 110.0)))

        # If no data yet return a sensible empty structure
        if not labels:
            labels    = [f"T{i}" for i in range(1, limit + 1)]
            hr_values = []
            bp_values = []

        return success({
            "labels":        labels,
            "heartRate":     hr_values,
            "bloodPressure": bp_values,
            "dataPoints":    len(labels),
        })

    except Exception as exc:
        logger.error("GET /dashboard/vitals-trend failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve vitals trend data.")
