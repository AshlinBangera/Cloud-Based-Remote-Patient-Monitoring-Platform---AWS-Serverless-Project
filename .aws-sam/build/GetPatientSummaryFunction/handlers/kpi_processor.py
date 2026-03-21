"""
src/handlers/kpi_processor.py
──────────────────────────────
Lambda handler triggered by DynamoDB Streams on TelemetryEventsTable.

Flow for each batch of stream records:
  1. Extract unique patientIds from NEW_IMAGE records
  2. For each patient, fetch recent events from DynamoDB
  3. Recompute all KPIs using aggregation_service
  4. Write updated summary to PatientSummariesTable
  5. Recompute top-level dashboard KPIs across all patients
  6. Write dashboard aggregates to DashboardAggregatesTable
  7. Publish CloudWatch metrics
"""

import json
import logging
import os
from datetime import datetime, timezone

from services.dynamodb_service import (
    get_recent_events_for_patient,
    put_patient_summary,
    get_all_patient_summaries,
    put_aggregate,
)
from services.aggregation_service import (
    compute_patient_summary,
    compute_dashboard_kpis,
    is_abnormal_event,
)
from services.metrics_service import publish_kpi_metrics
from utils.time_buckets import (
    get_heatmap_bucket,
    get_day_of_week,
    get_hour_label,
    now_utc_iso,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Aggregates TTL: 48 hours
_AGGREGATE_TTL_SECONDS = 48 * 60 * 60


def lambda_handler(event: dict, context) -> dict:
    """
    Entry point for DynamoDB Streams trigger.

    Args:
        event:   DynamoDB Streams event with Records list.
        context: Lambda context object.

    Returns:
        Summary dict of processed records.
    """
    records = event.get("Records", [])
    logger.info("KPI processor received %d stream records", len(records))

    # ── 1. Extract unique patients and new events from stream ─────────────────
    patient_ids: set[str] = set()
    new_events: list[dict] = []

    for record in records:
        if record.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue

        patient_id = _ddb_str(new_image.get("patientId"))
        if patient_id:
            patient_ids.add(patient_id)

        # Deserialise the stream image for heatmap/sync aggregation
        event_doc = _deserialise_image(new_image)
        if event_doc:
            new_events.append(event_doc)

    if not patient_ids:
        logger.info("No actionable records in batch — skipping.")
        return {"processed": 0}

    logger.info("Recomputing KPIs for patients: %s", sorted(patient_ids))

    # ── 2. Recompute per-patient summaries ────────────────────────────────────
    for patient_id in patient_ids:
        try:
            recent = get_recent_events_for_patient(patient_id, limit=200)
            summary = compute_patient_summary(patient_id, recent)
            put_patient_summary(summary)
            logger.info(
                "Updated summary for %s | txRate=%.1f%% adherence=%.1f%%",
                patient_id,
                summary.get("transmissionSuccessRate", 0),
                summary.get("adherenceScore", 0),
            )
        except Exception as exc:
            logger.error("Failed to update summary for %s: %s", patient_id, exc, exc_info=True)

    # ── 3. Recompute top-level dashboard KPIs ─────────────────────────────────
    try:
        all_summaries = get_all_patient_summaries()
        dashboard_kpis = compute_dashboard_kpis(all_summaries)
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        now_str   = now_utc_iso()

        put_aggregate(
            metric_type = "dashboard-kpis",
            period_key  = f"dashboard-kpis#{now_str[:13]}",   # hourly
            data        = dashboard_kpis,
            ttl         = now_epoch + _AGGREGATE_TTL_SECONDS,
        )
        logger.info("Dashboard KPIs updated: %s", dashboard_kpis)
    except Exception as exc:
        logger.error("Failed to update dashboard KPIs: %s", exc, exc_info=True)

    # ── 4. Update sync-frequency aggregate (hourly buckets) ───────────────────
    try:
        _update_sync_frequency(new_events)
    except Exception as exc:
        logger.warning("Sync frequency update failed: %s", exc)

    # ── 5. Update vitals-trend aggregate ──────────────────────────────────────
    try:
        _update_vitals_trend(new_events)
    except Exception as exc:
        logger.warning("Vitals trend update failed: %s", exc)

    # ── 6. Update heatmap aggregate ───────────────────────────────────────────
    try:
        _update_heatmap(new_events)
    except Exception as exc:
        logger.warning("Heatmap update failed: %s", exc)

    # ── 7. Publish CloudWatch metrics ─────────────────────────────────────────
    try:
        publish_kpi_metrics(dashboard_kpis)
    except Exception as exc:
        logger.warning("CloudWatch metrics publish failed: %s", exc)

    return {"processed": len(patient_ids), "events": len(new_events)}


# ── Aggregate helpers ─────────────────────────────────────────────────────────

def _update_sync_frequency(events: list) -> None:
    """Increment hourly sync-frequency counters for each new event."""
    if not events:
        return
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Group events by hour label
    buckets: dict[str, int] = {}
    for ev in events:
        ts = ev.get("timestamp", now_utc_iso())
        try:
            hour = get_hour_label(ts)
        except Exception:
            hour = now_utc_iso()[11:16]
        buckets[hour] = buckets.get(hour, 0) + 1

    for hour_label, count in buckets.items():
        put_aggregate(
            metric_type = "sync-frequency",
            period_key  = f"sync-frequency#{hour_label}",
            data        = {"label": hour_label, "count": count},
            ttl         = now_epoch + _AGGREGATE_TTL_SECONDS,
        )


def _update_vitals_trend(events: list) -> None:
    """Store average vitals for the current time bucket."""
    if not events:
        return
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    now_str   = now_utc_iso()

    hr_vals  = [float(e["heartRate"])  for e in events if "heartRate"  in e]
    bp_vals  = [float(e["systolicBP"]) for e in events if "systolicBP" in e]

    if not hr_vals:
        return

    avg_hr = round(sum(hr_vals) / len(hr_vals), 1)
    avg_bp = round(sum(bp_vals) / len(bp_vals), 1) if bp_vals else 0.0

    put_aggregate(
        metric_type = "vitals-trend",
        period_key  = f"vitals-trend#{now_str[:16]}",   # minute resolution
        data        = {
            "label":     now_str[11:16],
            "heartRate": avg_hr,
            "bloodPressure": avg_bp,
        },
        ttl = now_epoch + _AGGREGATE_TTL_SECONDS,
    )


def _update_heatmap(events: list) -> None:
    """Increment the heatmap cell for each abnormal event."""
    if not events:
        return
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    for ev in events:
        if not is_abnormal_event(ev):
            continue
        ts = ev.get("timestamp", now_utc_iso())
        try:
            day    = get_day_of_week(ts)
            bucket = get_heatmap_bucket(ts)
        except Exception:
            continue

        put_aggregate(
            metric_type = "heatmap",
            period_key  = f"heatmap#{day}#{bucket}",
            data        = {"day": day, "bucket": bucket, "count": 1},
            ttl         = now_epoch + _AGGREGATE_TTL_SECONDS,
        )


# ── DynamoDB stream deserialiser ──────────────────────────────────────────────

def _ddb_str(attr: dict | None) -> str | None:
    """Extract a string value from a DynamoDB attribute dict."""
    if not attr:
        return None
    return attr.get("S") or attr.get("s")


def _ddb_num(attr: dict | None) -> float | None:
    """Extract a numeric value from a DynamoDB attribute dict."""
    if not attr:
        return None
    val = attr.get("N") or attr.get("n")
    return float(val) if val is not None else None


def _deserialise_image(image: dict) -> dict | None:
    """
    Convert a DynamoDB stream NewImage (typed attributes) into a plain dict.
    Only extracts the fields needed for aggregation.
    """
    try:
        return {
            "patientId":          _ddb_str(image.get("patientId")),
            "deviceId":           _ddb_str(image.get("deviceId")),
            "timestamp":          _ddb_str(image.get("timestamp")),
            "heartRate":          _ddb_num(image.get("heartRate"))          or 75.0,
            "spo2":               _ddb_num(image.get("spo2"))               or 98.0,
            "systolicBP":         _ddb_num(image.get("systolicBP"))         or 120.0,
            "diastolicBP":        _ddb_num(image.get("diastolicBP"))        or 80.0,
            "batteryLevel":       _ddb_num(image.get("batteryLevel"))       or 100.0,
            "signalStrength":     _ddb_num(image.get("signalStrength"))     or -60.0,
            "transmissionStatus": _ddb_str(image.get("transmissionStatus")) or "success",
            "syncStatus":         _ddb_str(image.get("syncStatus"))         or "synced",
            "eventType":          _ddb_str(image.get("eventType"))          or "vitals",
        }
    except Exception as exc:
        logger.warning("Failed to deserialise stream image: %s", exc)
        return None
