"""
src/services/s3_service.py
───────────────────────────
Raw telemetry event archival to S3.
Events are stored as partitioned JSON files compatible
with Athena's Hive-style partition projection:

  s3://bucket/events/year=YYYY/month=MM/day=DD/hour=HH/<patientId>/<eventId>.json
"""

import os
import json
import logging
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)

RAW_EVENTS_BUCKET = os.environ.get(
    "RAW_EVENTS_BUCKET",
    "rhythmcloud-raw-events-dev"
)

_s3 = boto3.client("s3")


def _build_s3_key(patient_id: str, event_id: str, timestamp: str) -> str:
    """
    Build the partitioned S3 key for a telemetry event.

    Format:
        events/year=2026/month=03/day=20/hour=14/<patientId>/<eventId>.json
    """
    # Parse timestamp — strip trailing Z for fromisoformat compatibility
    ts_clean = timestamp.rstrip("Z").split("+")[0].split("-")
    try:
        dt = datetime.fromisoformat(timestamp.rstrip("Z")).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        dt = datetime.now(timezone.utc)

    return (
        f"events/"
        f"year={dt.year}/"
        f"month={dt.month:02d}/"
        f"day={dt.day:02d}/"
        f"hour={dt.hour:02d}/"
        f"{patient_id}/"
        f"{event_id}.json"
    )


def archive_event(event: dict) -> str:
    """
    Archive a single telemetry event to S3 as JSON.

    Args:
        event: The full telemetry event dict (already validated).

    Returns:
        The S3 key where the event was written.

    Raises:
        Exception: Propagates any S3 put errors to the caller.
    """
    patient_id = event["patientId"]
    event_id   = event["eventId"]
    timestamp  = event["timestamp"]

    key  = _build_s3_key(patient_id, event_id, timestamp)
    body = json.dumps(event, default=str)

    _s3.put_object(
        Bucket      = RAW_EVENTS_BUCKET,
        Key         = key,
        Body        = body.encode("utf-8"),
        ContentType = "application/json",
        # Server-side encryption is set at the bucket level
    )

    logger.info(
        "Archived event %s to s3://%s/%s",
        event_id, RAW_EVENTS_BUCKET, key
    )
    return key
