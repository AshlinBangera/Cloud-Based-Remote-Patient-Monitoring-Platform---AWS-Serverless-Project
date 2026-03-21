"""
src/handlers/ingest_event.py
─────────────────────────────
Lambda handler for POST /events

Flow:
  1. Parse and validate the JSON payload
  2. Enrich with a UUID event ID and ingestion timestamp
  3. Write to DynamoDB TelemetryEventsTable
  4. Archive raw event to S3 (partitioned by date/hour)
  5. Write to RecentEvents ring-buffer for the dashboard table
  6. Update DeviceStatus snapshot
  7. Publish per-event CloudWatch metrics
  8. Return 201 Created with the event ID

DynamoDB Streams picks up the new TelemetryEvents item and
triggers the KPI processor Lambda asynchronously.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from utils.validator      import validate_event, ValidationError
from utils.response       import created, bad_request, internal_error, options_response
from utils.time_buckets   import now_utc_iso
from services.dynamodb_service import (
    put_event,
    put_recent_event,
    put_device_status,
)
from services.s3_service          import archive_event
from services.metrics_service     import publish_ingest_metrics
from services.aggregation_service import is_abnormal_event
from services.alerting_service    import publish_alert

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# TTL for RecentEvents items: 24 hours from ingestion
_RECENT_EVENTS_TTL_SECONDS = 24 * 60 * 60


def lambda_handler(event: dict, context) -> dict:
    """
    Entry point for POST /events

    Args:
        event:   API Gateway Lambda proxy event dict.
        context: Lambda context object.

    Returns:
        API Gateway Lambda proxy response dict.
    """
    # Handle CORS preflight
    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info(
        "Ingest request received | requestId=%s",
        event.get("requestContext", {}).get("requestId", "local")
    )

    # ── 1. Parse request body ─────────────────────────────────────────────────
    raw_body = event.get("body", "")
    if not raw_body:
        return bad_request("Request body is required.")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON body: %s", exc)
        return bad_request(f"Invalid JSON: {exc}")

    # ── 2. Validate ───────────────────────────────────────────────────────────
    try:
        payload = validate_event(payload)
    except ValidationError as exc:
        logger.warning("Validation failed: %s | field=%s", exc.message, exc.field)
        return bad_request(exc.message, field=exc.field)

    # ── 3. Enrich with server-side metadata ───────────────────────────────────
    event_id        = str(uuid.uuid4())
    ingestion_time  = now_utc_iso()
    now_epoch       = int(datetime.now(timezone.utc).timestamp())

    # TTL: keep events in DynamoDB for 90 days
    ttl_epoch = now_epoch + (90 * 24 * 60 * 60)

    telemetry_item = {
        **payload,
        "eventId":       event_id,
        "ingestedAt":    ingestion_time,
        "ttl":           ttl_epoch,
        # Normalise enums to lowercase for consistent querying
        "transmissionStatus": payload["transmissionStatus"].lower(),
        "syncStatus":         payload["syncStatus"].lower(),
        "eventType":          payload["eventType"].lower(),
    }

    # ── 4. Write to DynamoDB TelemetryEventsTable ─────────────────────────────
    try:
        put_event(telemetry_item)
    except Exception as exc:
        logger.error("DynamoDB put_event failed: %s", exc, exc_info=True)
        return internal_error("Failed to store telemetry event.")

    # ── 5. Archive raw event to S3 ────────────────────────────────────────────
    try:
        s3_key = archive_event(telemetry_item)
    except Exception as exc:
        # S3 archival failure is non-fatal: event is already in DynamoDB
        logger.warning("S3 archive failed (non-fatal): %s", exc)
        s3_key = None

    # ── 6. Write to RecentEvents ring-buffer ──────────────────────────────────
    try:
        recent_ttl  = now_epoch + _RECENT_EVENTS_TTL_SECONDS
        sort_key    = f"{ingestion_time}#{event_id}"
        recent_item = {
            "time":       ingestion_time[11:23],  # HH:MM:SS.mmm
            "patientId":  payload["patientId"],
            "deviceId":   payload["deviceId"],
            "eventType":  _event_type_label(payload["eventType"]),
            "status":     _status_label(payload["transmissionStatus"]),
            "heartRate":  payload["heartRate"],
            "spo2":       payload["spo2"],
            "batteryLevel": payload["batteryLevel"],
        }
        put_recent_event(sort_key, recent_item, recent_ttl)
    except Exception as exc:
        logger.warning("RecentEvents write failed (non-fatal): %s", exc)

    # ── 7. Update DeviceStatus snapshot ──────────────────────────────────────
    try:
        put_device_status(payload["deviceId"], {
            "patientId":          payload["patientId"],
            "lastSeen":           ingestion_time,
            "batteryLevel":       payload["batteryLevel"],
            "signalStrength":     payload["signalStrength"],
            "transmissionStatus": payload["transmissionStatus"].lower(),
            "syncStatus":         payload["syncStatus"].lower(),
            "lastEventType":      payload["eventType"].lower(),
        })
    except Exception as exc:
        logger.warning("DeviceStatus update failed (non-fatal): %s", exc)

    # ── 8. Publish CloudWatch metrics ─────────────────────────────────────────
    try:
        publish_ingest_metrics(telemetry_item)
    except Exception as exc:
        logger.warning("CloudWatch metrics publish failed (non-fatal): %s", exc)

    # ── 9. Publish SNS alert if event is abnormal ─────────────────────────────
    alert_sent = False
    if is_abnormal_event(telemetry_item):
        try:
            alert_sent = publish_alert(telemetry_item)
            if alert_sent:
                logger.info(
                    "Clinical alert sent | patientId=%s eventId=%s",
                    payload["patientId"], event_id
                )
        except Exception as exc:
            logger.warning("Alert publish failed (non-fatal): %s", exc)

    # ── 10. Return 201 Created ────────────────────────────────────────────────
    logger.info(
        "Event ingested | eventId=%s patientId=%s abnormal=%s alertSent=%s",
        event_id, payload["patientId"],
        is_abnormal_event(telemetry_item), alert_sent,
    )

    return created({
        "message":    "Event ingested successfully.",
        "eventId":    event_id,
        "patientId":  payload["patientId"],
        "deviceId":   payload["deviceId"],
        "timestamp":  payload["timestamp"],
        "ingestedAt": ingestion_time,
        "s3Key":      s3_key,
        "alertSent":  alert_sent,
    })


# ── Label helpers ─────────────────────────────────────────────────────────────

def _event_type_label(event_type: str) -> str:
    """Map internal event type to a human-readable dashboard label."""
    labels = {
        "vitals":        "Vitals Update",
        "alert":         "Abnormal Beat",
        "device_health": "Device Health",
        "sync":          "Data Sync",
        "battery":       "Battery Low",
    }
    return labels.get(event_type.lower(), event_type.title())


def _status_label(transmission_status: str) -> str:
    """Map transmission status to a dashboard status pill value."""
    mapping = {
        "success": "successful",
        "failed":  "failed",
        "pending": "alerted",
    }
    return mapping.get(transmission_status.lower(), "alerted")
