"""
src/handlers/acknowledge_alert.py
───────────────────────────────────
Lambda handler for POST /alerts/{alertId}/acknowledge

Called by a clinician when they have reviewed and actioned an alert.
Records the acknowledgement time and computes the response time metric.

Request body (optional):
  { "acknowledgedBy": "Dr. Smith" }

Response (200):
  {
    "alertId":          "uuid",
    "patientId":        "P001",
    "alertType":        "TACHYCARDIA",
    "severity":         "HIGH",
    "status":           "ACKNOWLEDGED",
    "detectedAt":       "2026-03-21T06:00:00Z",
    "acknowledgedAt":   "2026-03-21T06:04:32Z",
    "responseTimeSec":  272,
    "responseTimeLabel": "4m 32s"
  }
"""

import json
import logging
import os

import boto3

from services.alerts_db_service import acknowledge_alert, get_alert
from utils.response import success, not_found, bad_request, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "RhythmCloud")
_cw = boto3.client("cloudwatch")


def lambda_handler(event: dict, context) -> dict:
    """Entry point for POST /alerts/{alertId}/acknowledge"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    path_params = event.get("pathParameters") or {}
    alert_id    = path_params.get("alertId", "").strip()

    if not alert_id:
        return bad_request("Path parameter 'alertId' is required.")

    # Parse optional body
    acknowledged_by = "clinician"
    raw_body = event.get("body", "")
    if raw_body:
        try:
            body            = json.loads(raw_body)
            acknowledged_by = body.get("acknowledgedBy", "clinician")
        except json.JSONDecodeError:
            pass

    logger.info("POST /alerts/%s/acknowledge by %s", alert_id, acknowledged_by)

    try:
        # Check alert exists
        existing = get_alert(alert_id)
        if not existing:
            return not_found("Alert", alert_id)

        # Acknowledge and compute response time
        updated = acknowledge_alert(alert_id, acknowledged_by)
        if not updated:
            return not_found("Alert", alert_id)

        response_time_sec = updated.get("responseTimeSec", 0)

        # Publish response time metric to CloudWatch
        try:
            _cw.put_metric_data(
                Namespace  = CLOUDWATCH_NAMESPACE,
                MetricData = [{
                    "MetricName": "AlertResponseTimeSeconds",
                    "Value":      float(response_time_sec),
                    "Unit":       "Seconds",
                    "Dimensions": [
                        {"Name": "Severity",  "Value": updated.get("severity",  "UNKNOWN")},
                        {"Name": "AlertType", "Value": updated.get("alertType", "UNKNOWN")},
                    ],
                }],
            )
            logger.info(
                "Published AlertResponseTimeSeconds=%d | alertId=%s",
                response_time_sec, alert_id
            )
        except Exception as cw_exc:
            logger.warning("CloudWatch metric publish failed: %s", cw_exc)

        # Build human-readable response time label
        updated["responseTimeLabel"] = _format_response_time(response_time_sec)

        return success(updated)

    except Exception as exc:
        logger.error(
            "POST /alerts/%s/acknowledge failed: %s", alert_id, exc, exc_info=True
        )
        return internal_error("Failed to acknowledge alert.")


def _format_response_time(seconds: int) -> str:
    """Convert seconds into a human-readable label: '4m 32s', '1h 2m', etc."""
    if seconds < 0:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    return f"{h}h {m}m"
