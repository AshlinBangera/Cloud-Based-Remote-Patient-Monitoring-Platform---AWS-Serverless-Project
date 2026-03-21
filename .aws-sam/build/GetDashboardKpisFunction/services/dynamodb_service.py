"""
src/services/dynamodb_service.py
─────────────────────────────────
All DynamoDB operations for RhythmCloud.
Uses resource-level client with Decimal handling for
numeric attributes returned by DynamoDB.
"""

import os
import json
import logging
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

# ── Table name constants (injected via Lambda env vars) ───────────────────────
EVENTS_TABLE       = os.environ.get("EVENTS_TABLE",       "rhythmcloud-telemetry-events-dev")
SUMMARIES_TABLE    = os.environ.get("SUMMARIES_TABLE",    "rhythmcloud-patient-summaries-dev")
AGGREGATES_TABLE   = os.environ.get("AGGREGATES_TABLE",   "rhythmcloud-dashboard-aggregates-dev")
RECENT_EVENTS_TABLE = os.environ.get("RECENT_EVENTS_TABLE", "rhythmcloud-recent-events-dev")
DEVICE_STATUS_TABLE = os.environ.get("DEVICE_STATUS_TABLE", "rhythmcloud-device-status-dev")

# Singleton DynamoDB resource (reused across warm invocations)
_dynamodb = boto3.resource("dynamodb")


def _table(name: str):
    return _dynamodb.Table(name)


def _to_decimal(obj: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def _from_decimal(obj: Any) -> Any:
    """Recursively convert DynamoDB Decimals back to float/int for JSON."""
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 != 0 else int(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(i) for i in obj]
    return obj


# ── TelemetryEvents ───────────────────────────────────────────────────────────

def put_event(item: dict) -> None:
    """Write a single telemetry event to TelemetryEventsTable."""
    table = _table(EVENTS_TABLE)
    table.put_item(Item=_to_decimal(item))
    logger.info("Wrote event %s for patient %s",
                item.get("eventId"), item.get("patientId"))


def get_patient_events(
    patient_id: str,
    limit: int = 50,
    last_evaluated_key: dict | None = None,
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
) -> dict:
    """
    Query events for a patient ordered by timestamp (newest first).

    Returns:
        {
            "items":             [...],
            "lastEvaluatedKey":  {...} | None,
            "count":             int
        }
    """
    table = _table(EVENTS_TABLE)
    kwargs: dict = {
        "IndexName":              "PatientTimestampIndex",
        "KeyConditionExpression": Key("patientId").eq(patient_id),
        "ScanIndexForward":       False,
        "Limit":                  limit,
    }

    # Optional timestamp range filter
    if start_timestamp and end_timestamp:
        kwargs["KeyConditionExpression"] = (
            Key("patientId").eq(patient_id)
            & Key("timestamp").between(start_timestamp, end_timestamp)
        )
    elif start_timestamp:
        kwargs["KeyConditionExpression"] = (
            Key("patientId").eq(patient_id)
            & Key("timestamp").gte(start_timestamp)
        )

    if last_evaluated_key:
        kwargs["ExclusiveStartKey"] = last_evaluated_key

    response = table.query(**kwargs)
    return {
        "items":            _from_decimal(response.get("Items", [])),
        "lastEvaluatedKey": response.get("LastEvaluatedKey"),
        "count":            response.get("Count", 0),
    }


def get_recent_events_for_patient(patient_id: str, limit: int = 100) -> list:
    """Return the most recent N events for a patient (used by KPI processor)."""
    result = get_patient_events(patient_id, limit=limit)
    return result["items"]


# ── PatientSummaries ──────────────────────────────────────────────────────────

def get_patient_summary(patient_id: str) -> dict | None:
    """Retrieve the KPI summary for a patient. Returns None if not found."""
    table = _table(SUMMARIES_TABLE)
    response = table.get_item(Key={"patientId": patient_id})
    item = response.get("Item")
    return _from_decimal(item) if item else None


def put_patient_summary(summary: dict) -> None:
    """Write/overwrite the KPI summary for a patient."""
    table = _table(SUMMARIES_TABLE)
    table.put_item(Item=_to_decimal(summary))
    logger.info("Updated summary for patient %s", summary.get("patientId"))


def get_all_patient_summaries() -> list:
    """Scan all patient summaries (used by dashboard adherence endpoint)."""
    table = _table(SUMMARIES_TABLE)
    response = table.scan()
    items = response.get("Items", [])
    # Handle pagination for large datasets
    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        items.extend(response.get("Items", []))
    return _from_decimal(items)


# ── DashboardAggregates ───────────────────────────────────────────────────────

def put_aggregate(metric_type: str, period_key: str, data: dict, ttl: int) -> None:
    """
    Write a pre-aggregated dashboard metric.

    Args:
        metric_type: e.g. 'sync-frequency', 'vitals-trend', 'heatmap'
        period_key:  e.g. 'sync-frequency#2026-03-20T14'
        data:        Serialisable dict of the metric payload
        ttl:         Unix timestamp when this record should expire
    """
    table = _table(AGGREGATES_TABLE)
    item  = {
        "metricType": metric_type,
        "periodKey":  period_key,
        "data":       json.dumps(data),
        "ttl":        ttl,
    }
    table.put_item(Item=item)


def get_aggregates(metric_type: str, limit: int = 24) -> list:
    """
    Query the most recent N aggregate records for a metric type.

    Returns a list of dicts with 'periodKey' and 'data' keys.
    """
    table = _table(AGGREGATES_TABLE)
    response = table.query(
        KeyConditionExpression=Key("metricType").eq(metric_type),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = response.get("Items", [])
    result = []
    for item in items:
        try:
            result.append({
                "periodKey": item["periodKey"],
                "data":      json.loads(item["data"]),
            })
        except (KeyError, json.JSONDecodeError) as exc:
            logger.warning("Skipping malformed aggregate item: %s", exc)
    return result


# ── RecentEvents ──────────────────────────────────────────────────────────────

def put_recent_event(sort_key: str, event: dict, ttl: int) -> None:
    """
    Write an event to the RecentEvents ring-buffer table.

    Args:
        sort_key: 'timestamp#eventId' (ensures time-ordered sort)
        event:    Formatted event dict for the dashboard table
        ttl:      Unix epoch expiry (24h from now)
    """
    table = _table(RECENT_EVENTS_TABLE)
    table.put_item(Item={
        "partitionKey": "RECENT",
        "sortKey":      sort_key,
        "ttl":          ttl,
        **_to_decimal(event),
    })


def get_recent_events(limit: int = 20) -> list:
    """
    Return the most recent N events from the ring-buffer table,
    ordered newest first.
    """
    table = _table(RECENT_EVENTS_TABLE)
    response = table.query(
        KeyConditionExpression=Key("partitionKey").eq("RECENT"),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = response.get("Items", [])
    # Strip internal keys before returning to the dashboard
    clean = []
    for item in items:
        item.pop("partitionKey", None)
        item.pop("sortKey",      None)
        item.pop("ttl",          None)
        clean.append(_from_decimal(item))
    return clean


# ── DeviceStatus ──────────────────────────────────────────────────────────────

def put_device_status(device_id: str, status: dict) -> None:
    """Update the latest known status snapshot for a device."""
    table = _table(DEVICE_STATUS_TABLE)
    table.put_item(Item={
        "deviceId": device_id,
        **_to_decimal(status),
    })


def get_device_status(device_id: str) -> dict | None:
    """Retrieve the latest status for a device. Returns None if not found."""
    table = _table(DEVICE_STATUS_TABLE)
    response = table.get_item(Key={"deviceId": device_id})
    item = response.get("Item")
    return _from_decimal(item) if item else None
