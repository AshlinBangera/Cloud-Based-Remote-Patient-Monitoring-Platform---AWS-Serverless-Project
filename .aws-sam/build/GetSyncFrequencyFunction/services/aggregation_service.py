"""
src/services/aggregation_service.py
─────────────────────────────────────
KPI computation logic for the RhythmCloud platform.

Called by the KPI processor Lambda after each new event arrives
via DynamoDB Streams. Reads recent events, recomputes all KPIs,
and returns structured summaries ready to write back to DynamoDB.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Abnormal thresholds ────────────────────────────────────────────────────────
HEART_RATE_LOW  = 50
HEART_RATE_HIGH = 130
SPO2_LOW        = 90
BATTERY_LOW     = 20
SIGNAL_WEAK     = -95   # dBm


def is_abnormal_event(event: dict) -> bool:
    """
    Return True if the event contains any abnormal clinical indicator.

    Triggers:
    - Heart rate outside 50–130 bpm
    - SpO2 below 90%
    - Transmission failure
    - Sync failure
    - Battery below 20%
    - Weak signal strength below -95 dBm
    """
    if event.get("transmissionStatus", "").lower() == "failed":
        return True
    if event.get("syncStatus", "").lower() == "failed":
        return True

    hr  = float(event.get("heartRate",      75))
    spo = float(event.get("spo2",           99))
    bat = float(event.get("batteryLevel",   100))
    sig = float(event.get("signalStrength",  -60))

    if hr < HEART_RATE_LOW or hr > HEART_RATE_HIGH:
        return True
    if spo < SPO2_LOW:
        return True
    if bat < BATTERY_LOW:
        return True
    if sig < SIGNAL_WEAK:
        return True

    return False


def compute_patient_summary(patient_id: str, events: list) -> dict:
    """
    Compute all KPIs for a patient from their recent event history.

    Args:
        patient_id: Patient identifier.
        events:     List of recent telemetry event dicts (newest first).

    Returns:
        A summary dict ready to write to PatientSummariesTable.
    """
    if not events:
        return _empty_summary(patient_id)

    total       = len(events)
    abnormal    = sum(1 for e in events if is_abnormal_event(e))
    tx_success  = sum(
        1 for e in events
        if e.get("transmissionStatus", "").lower() == "success"
    )
    tx_failed   = sum(
        1 for e in events
        if e.get("transmissionStatus", "").lower() == "failed"
    )
    sync_ok     = sum(
        1 for e in events
        if e.get("syncStatus", "").lower() == "synced"
    )
    sync_failed = sum(
        1 for e in events
        if e.get("syncStatus", "").lower() == "failed"
    )
    battery_low = sum(
        1 for e in events
        if float(e.get("batteryLevel", 100)) < BATTERY_LOW
    )

    # Transmission success rate (%)
    tx_success_rate = round((tx_success / total) * 100, 1) if total else 0.0

    # Device sync reliability (%)
    sync_reliability = round((sync_ok / total) * 100, 1) if total else 0.0

    # Abnormal event frequency (per 100 events)
    abnormal_freq = round((abnormal / total) * 100, 1) if total else 0.0

    # Patient adherence: ratio of events with successful transmission
    # and valid vitals over expected events (proxy metric)
    adherence = round(
        ((total - abnormal) / total) * 100, 1
    ) if total else 0.0

    # Average vitals (last 20 events)
    recent_20    = events[:20]
    avg_hr       = _safe_avg(recent_20, "heartRate")
    avg_spo2     = _safe_avg(recent_20, "spo2")
    avg_systolic = _safe_avg(recent_20, "systolicBP")
    avg_diastolic = _safe_avg(recent_20, "diastolicBP")
    avg_battery  = _safe_avg(recent_20, "batteryLevel")

    # Latest event metadata
    latest = events[0]

    return {
        "patientId":              patient_id,
        "totalEvents":            total,
        "abnormalEventCount":     abnormal,
        "abnormalEventFrequency": abnormal_freq,
        "transmissionSuccessRate": tx_success_rate,
        "transmissionFailures":   tx_failed,
        "syncReliability":        sync_reliability,
        "syncFailures":           sync_failed,
        "adherenceScore":         adherence,
        "batteryLowCount":        battery_low,
        "avgHeartRate":           avg_hr,
        "avgSpo2":                avg_spo2,
        "avgSystolicBP":          avg_systolic,
        "avgDiastolicBP":         avg_diastolic,
        "avgBatteryLevel":        avg_battery,
        "lastEventTimestamp":     latest.get("timestamp", ""),
        "lastDeviceId":           latest.get("deviceId", ""),
        "lastTransmissionStatus": latest.get("transmissionStatus", ""),
        "lastSyncStatus":         latest.get("syncStatus", ""),
        "lastEventType":          latest.get("eventType", ""),
    }


def compute_dashboard_kpis(all_summaries: list) -> dict:
    """
    Aggregate across all patient summaries to produce top-level
    dashboard KPI values for the GET /dashboard/kpis endpoint.

    Args:
        all_summaries: List of PatientSummary dicts from DynamoDB.

    Returns:
        KPI dict matching the dashboard gauge/card payload schemas.
    """
    if not all_summaries:
        return _empty_dashboard_kpis()

    n = len(all_summaries)

    avg_tx_rate     = _avg_field(all_summaries, "transmissionSuccessRate")
    avg_sync_rel    = _avg_field(all_summaries, "syncReliability")
    total_abnormal  = sum(int(s.get("abnormalEventCount", 0)) for s in all_summaries)
    total_tx_fail   = sum(int(s.get("transmissionFailures", 0)) for s in all_summaries)
    total_sync_fail = sum(int(s.get("syncFailures", 0)) for s in all_summaries)
    avg_adherence   = _avg_field(all_summaries, "adherenceScore")

    # Most recent sync time across all patients
    timestamps = [
        s.get("lastEventTimestamp", "")
        for s in all_summaries
        if s.get("lastEventTimestamp")
    ]
    last_sync_time = max(timestamps) if timestamps else ""

    return {
        "transmissionSuccessRate": {
            "value":          round(avg_tx_rate, 1),
            "trendDelta":     0.3,       # placeholder — real delta needs history
            "trendDirection": "up",
        },
        "syncReliability": {
            "status":       "Operational" if avg_sync_rel >= 90 else "Degraded",
            "lastSyncTime": last_sync_time,
            "avgLatencyMs": 34,          # placeholder — populate from CloudWatch
            "syncFailures": total_sync_fail,
            "queueDepth":   0,
        },
        "abnormalEvents": {
            "count24h":       total_abnormal,
            "requiresReview": max(0, total_abnormal - 2),
        },
        "adherenceScore":        round(avg_adherence, 1),
        "transmissionFailures":  total_tx_fail,
        "syncFailures":          total_sync_fail,
        "patientCount":          n,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_avg(events: list, field: str) -> float:
    """Return the average of a numeric field across events. Returns 0.0 if empty."""
    values = [float(e[field]) for e in events if field in e]
    return round(sum(values) / len(values), 1) if values else 0.0


def _avg_field(items: list, field: str) -> float:
    """Average a numeric field across a list of dicts."""
    values = [float(i.get(field, 0)) for i in items]
    return round(sum(values) / len(values), 1) if values else 0.0


def _empty_summary(patient_id: str) -> dict:
    return {
        "patientId":               patient_id,
        "totalEvents":             0,
        "abnormalEventCount":      0,
        "abnormalEventFrequency":  0.0,
        "transmissionSuccessRate": 0.0,
        "transmissionFailures":    0,
        "syncReliability":         0.0,
        "syncFailures":            0,
        "adherenceScore":          0.0,
        "batteryLowCount":         0,
        "avgHeartRate":            0.0,
        "avgSpo2":                 0.0,
        "avgSystolicBP":           0.0,
        "avgDiastolicBP":          0.0,
        "avgBatteryLevel":         0.0,
        "lastEventTimestamp":      "",
        "lastDeviceId":            "",
        "lastTransmissionStatus":  "",
        "lastSyncStatus":          "",
        "lastEventType":           "",
    }


def _empty_dashboard_kpis() -> dict:
    return {
        "transmissionSuccessRate": {
            "value": 0.0, "trendDelta": 0.0, "trendDirection": "flat"
        },
        "syncReliability": {
            "status": "Unknown", "lastSyncTime": "",
            "avgLatencyMs": 0, "syncFailures": 0, "queueDepth": 0,
        },
        "abnormalEvents":       {"count24h": 0, "requiresReview": 0},
        "adherenceScore":       0.0,
        "transmissionFailures": 0,
        "syncFailures":         0,
        "patientCount":         0,
    }
