"""
src/services/alerts_db_service.py
──────────────────────────────────
DynamoDB operations for the Alerts table.

Schema:
  PK: alertId (UUID)
  GSI: PatientAlertsIndex — PK: patientId, SK: detectedAt

Each alert record tracks:
  - detectedAt:      when the abnormal event was ingested
  - acknowledgedAt:  when a clinician called POST /alerts/{id}/acknowledge
  - responseTimeSec: acknowledgedAt - detectedAt in seconds
  - status:          ACTIVE | ACKNOWLEDGED
"""

import os
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

ALERTS_TABLE = os.environ.get("ALERTS_TABLE", "rhythmcloud-alerts-dev")
_dynamodb    = boto3.resource("dynamodb")


def _table():
    return _dynamodb.Table(ALERTS_TABLE)


def _from_decimal(obj):
    """Recursively convert Decimal back to int/float for JSON serialisation."""
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 != 0 else int(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(i) for i in obj]
    return obj


def put_alert(alert: dict) -> None:
    """Write a new alert record when an abnormal event is detected."""
    _table().put_item(Item=alert)
    logger.info(
        "Alert record created | alertId=%s patientId=%s type=%s",
        alert.get("alertId"), alert.get("patientId"), alert.get("alertType")
    )


def get_alert(alert_id: str) -> dict | None:
    """Retrieve a single alert by ID. Returns None if not found."""
    response = _table().get_item(Key={"alertId": alert_id})
    item = response.get("Item")
    return _from_decimal(item) if item else None


def acknowledge_alert(alert_id: str, acknowledged_by: str = "clinician") -> dict | None:
    """
    Mark an alert as acknowledged and compute response time.

    Returns the updated alert record, or None if not found.
    """
    now     = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch the current alert to compute response time
    alert = get_alert(alert_id)
    if not alert:
        return None

    if alert.get("status") == "ACKNOWLEDGED":
        # Already acknowledged — return existing record
        return alert

    # Compute response time in seconds
    try:
        detected_str = alert["detectedAt"]
        detected_dt  = datetime.fromisoformat(detected_str.rstrip("Z")).replace(
            tzinfo=timezone.utc
        )
        response_time_sec = int((now - detected_dt).total_seconds())
    except Exception as exc:
        logger.warning("Could not compute response time: %s", exc)
        response_time_sec = -1

    response = _table().update_item(
        Key={"alertId": alert_id},
        UpdateExpression="""
            SET #st             = :status,
                acknowledgedAt  = :ack_time,
                acknowledgedBy  = :ack_by,
                responseTimeSec = :rt
        """,
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":status":   "ACKNOWLEDGED",
            ":ack_time": now_iso,
            ":ack_by":   acknowledged_by,
            ":rt":       response_time_sec,
        },
        ReturnValues="ALL_NEW",
    )

    updated = _from_decimal(response.get("Attributes", {}))
    logger.info(
        "Alert acknowledged | alertId=%s responseTimeSec=%d",
        alert_id, response_time_sec
    )
    return updated


def get_patient_alerts(
    patient_id: str,
    status: str | None = None,
    limit: int = 20,
) -> list:
    """
    Query all alerts for a patient ordered by detectedAt (newest first).

    Args:
        patient_id: Patient identifier.
        status:     Optional filter — 'ACTIVE' or 'ACKNOWLEDGED'.
        limit:      Max number of alerts to return.

    Returns:
        List of alert dicts.
    """
    kwargs: dict = {
        "IndexName":              "PatientAlertsIndex",
        "KeyConditionExpression": Key("patientId").eq(patient_id),
        "ScanIndexForward":       False,
        "Limit":                  limit,
    }

    if status:
        kwargs["FilterExpression"] = boto3.dynamodb.conditions.Attr("status").eq(
            status.upper()
        )

    response = _table().query(**kwargs)
    return _from_decimal(response.get("Items", []))


def get_unacknowledged_alerts(limit: int = 50) -> list:
    """
    Scan for all ACTIVE (unacknowledged) alerts across all patients.
    Used by the dashboard to show pending alerts.
    """
    response = _table().scan(
        FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("ACTIVE"),
        Limit=limit,
    )
    items = _from_decimal(response.get("Items", []))
    # Sort by detectedAt descending
    return sorted(items, key=lambda x: x.get("detectedAt", ""), reverse=True)
