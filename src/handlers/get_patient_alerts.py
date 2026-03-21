"""
src/handlers/get_patient_alerts.py
────────────────────────────────────
Lambda handler for GET /patients/{patientId}/alerts

Returns all clinical alerts for a patient with response time stats.

Query params:
  ?status=ACTIVE|ACKNOWLEDGED   Filter by status (default: all)
  ?limit=20                     Max results (default 20, max 100)

Response:
  {
    "patientId":          "P001",
    "alerts":             [...],
    "totalAlerts":        12,
    "activeAlerts":       3,
    "acknowledgedAlerts": 9,
    "avgResponseTimeSec": 245,
    "avgResponseTimeLabel": "4m 5s",
    "fastestResponseSec": 42,
    "slowestResponseSec": 820
  }
"""

import logging
import os

from services.alerts_db_service import get_patient_alerts
from utils.response import success, not_found, bad_request, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_DEFAULT_LIMIT = 20
_MAX_LIMIT      = 100


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /patients/{patientId}/alerts"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    path_params = event.get("pathParameters") or {}
    patient_id  = path_params.get("patientId", "").strip()

    if not patient_id:
        return bad_request("Path parameter 'patientId' is required.")

    params = event.get("queryStringParameters") or {}
    status = params.get("status", "").upper() or None
    if status and status not in ("ACTIVE", "ACKNOWLEDGED"):
        return bad_request("'status' must be ACTIVE or ACKNOWLEDGED.")

    try:
        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except (ValueError, TypeError):
        limit = _DEFAULT_LIMIT

    logger.info("GET /patients/%s/alerts status=%s limit=%d", patient_id, status, limit)

    try:
        alerts = get_patient_alerts(patient_id, status=status, limit=limit)

        # Compute stats across returned alerts
        active       = [a for a in alerts if a.get("status") == "ACTIVE"]
        acknowledged = [a for a in alerts if a.get("status") == "ACKNOWLEDGED"]

        response_times = [
            int(a["responseTimeSec"])
            for a in acknowledged
            if a.get("responseTimeSec", -1) >= 0
        ]

        avg_rt     = round(sum(response_times) / len(response_times)) if response_times else None
        fastest_rt = min(response_times) if response_times else None
        slowest_rt = max(response_times) if response_times else None

        return success({
            "patientId":            patient_id,
            "alerts":               alerts,
            "totalAlerts":          len(alerts),
            "activeAlerts":         len(active),
            "acknowledgedAlerts":   len(acknowledged),
            "avgResponseTimeSec":   avg_rt,
            "avgResponseTimeLabel": _fmt(avg_rt),
            "fastestResponseSec":   fastest_rt,
            "slowestResponseSec":   slowest_rt,
        })

    except Exception as exc:
        logger.error(
            "GET /patients/%s/alerts failed: %s", patient_id, exc, exc_info=True
        )
        return internal_error("Failed to retrieve patient alerts.")


def _fmt(seconds: int | None) -> str:
    """Format seconds to human-readable string."""
    if seconds is None or seconds < 0:
        return "N/A"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, r = divmod(seconds, 3600)
    return f"{h}h {r // 60}m"
