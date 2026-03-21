"""
src/services/risk_scoring_service.py
──────────────────────────────────────
Patient risk scoring engine for RhythmCloud.

Computes a composite risk score (0–100) for each patient based on
their last 50 telemetry events. No ML framework needed — pure Python
clinical logic that mirrors real-world early warning scores (NEWS2).

Risk factors weighted and summed:
  - Abnormal event frequency     (30% weight)
  - Vitals trend direction        (25% weight)
  - Transmission reliability      (20% weight)
  - Battery / device health       (15% weight)
  - SpO2 average                  (10% weight)

Risk levels:
  0–24   → LOW      (green)
  25–49  → MEDIUM   (yellow)
  50–74  → HIGH     (orange)
  75–100 → CRITICAL (red)
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Weights (must sum to 1.0) ─────────────────────────────────────────────────
W_ABNORMAL_FREQ   = 0.30
W_VITALS_TREND    = 0.25
W_TX_RELIABILITY  = 0.20
W_DEVICE_HEALTH   = 0.15
W_SPO2            = 0.10

# ── Clinical thresholds ───────────────────────────────────────────────────────
HR_CRITICAL_HIGH  = 150
HR_HIGH           = 130
HR_LOW            = 50
HR_CRITICAL_LOW   = 40
SPO2_CRITICAL     = 85
SPO2_LOW          = 90
SBP_CRISIS        = 180
SBP_HIGH          = 160
BATTERY_CRITICAL  = 10
BATTERY_LOW       = 20


def compute_risk_score(patient_id: str, events: list) -> dict:
    """
    Compute a composite risk score for a patient from recent events.

    Args:
        patient_id: Patient identifier.
        events:     List of recent telemetry event dicts (newest first).

    Returns:
        Risk assessment dict with score, level, factors, and recommendations.
    """
    if not events:
        return _empty_risk(patient_id)

    n = len(events)

    # ── Factor 1: Abnormal event frequency (0–100) ────────────────────────────
    abnormal_count = sum(1 for e in events if _is_abnormal(e))
    abnormal_rate  = abnormal_count / n
    f_abnormal     = min(100, abnormal_rate * 100 * 2)  # 50% rate → 100 score

    # ── Factor 2: Vitals trend (0–100) ────────────────────────────────────────
    f_vitals = _score_vitals_trend(events)

    # ── Factor 3: Transmission reliability (0–100, inverted) ─────────────────
    tx_fail_count = sum(
        1 for e in events
        if e.get("transmissionStatus", "").lower() == "failed"
    )
    tx_fail_rate  = tx_fail_count / n
    f_tx          = min(100, tx_fail_rate * 100 * 3)  # 33% fail rate → 100 score

    # ── Factor 4: Device health (0–100) ───────────────────────────────────────
    f_device = _score_device_health(events)

    # ── Factor 5: SpO2 average (0–100, inverted from normal) ─────────────────
    spo2_vals = [float(e.get("spo2", 98)) for e in events if "spo2" in e]
    avg_spo2  = sum(spo2_vals) / len(spo2_vals) if spo2_vals else 98.0
    if avg_spo2 >= 95:
        f_spo2 = 0
    elif avg_spo2 >= 90:
        f_spo2 = (95 - avg_spo2) / 5 * 50     # 90–95% → 0–50 score
    else:
        f_spo2 = 50 + (90 - avg_spo2) / 5 * 50  # <90% → 50–100 score
    f_spo2 = min(100, max(0, f_spo2))

    # ── Composite score ───────────────────────────────────────────────────────
    raw_score = (
        f_abnormal  * W_ABNORMAL_FREQ +
        f_vitals    * W_VITALS_TREND  +
        f_tx        * W_TX_RELIABILITY+
        f_device    * W_DEVICE_HEALTH +
        f_spo2      * W_SPO2
    )
    score = round(min(100, max(0, raw_score)), 1)

    # ── Risk level ────────────────────────────────────────────────────────────
    level, color = _risk_level(score)

    # ── Latest vitals snapshot ────────────────────────────────────────────────
    latest = events[0]

    # ── Trend direction (last 5 vs previous 5 events) ─────────────────────────
    hr_trend  = _trend_direction(events, "heartRate",  5)
    spo2_trend = _trend_direction(events, "spo2", 5, invert=True)

    # ── Contributing factors for explanation ─────────────────────────────────
    factors = _build_factors(
        abnormal_rate, f_abnormal,
        tx_fail_rate,  f_tx,
        avg_spo2,      f_spo2,
        f_vitals,      f_device,
    )

    # ── Clinical recommendations ──────────────────────────────────────────────
    recommendations = _build_recommendations(level, factors, latest)

    return {
        "patientId":          patient_id,
        "riskScore":          score,
        "riskLevel":          level,
        "riskColor":          color,
        "eventsAnalysed":     n,
        "abnormalCount":      abnormal_count,
        "abnormalRate":       round(abnormal_rate * 100, 1),
        "avgSpo2":            round(avg_spo2, 1),
        "avgHeartRate":       round(
            sum(float(e.get("heartRate", 75)) for e in events) / n, 1
        ),
        "txFailureRate":      round(tx_fail_rate * 100, 1),
        "heartRateTrend":     hr_trend,
        "spo2Trend":          spo2_trend,
        "scoreBreakdown": {
            "abnormalFrequency":    round(f_abnormal,  1),
            "vitalsTrend":          round(f_vitals,    1),
            "txReliability":        round(f_tx,        1),
            "deviceHealth":         round(f_device,    1),
            "spo2Score":            round(f_spo2,      1),
        },
        "factors":            factors,
        "recommendations":    recommendations,
        "latestVitals": {
            "heartRate":   latest.get("heartRate",   0),
            "spo2":        latest.get("spo2",        0),
            "systolicBP":  latest.get("systolicBP",  0),
            "diastolicBP": latest.get("diastolicBP", 0),
            "batteryLevel":latest.get("batteryLevel",0),
            "lastSeen":    latest.get("timestamp",   ""),
        },
    }


# ── Internal scoring helpers ──────────────────────────────────────────────────

def _is_abnormal(event: dict) -> bool:
    """Return True if the event has any abnormal clinical indicator."""
    hr  = float(event.get("heartRate",      75))
    spo = float(event.get("spo2",           98))
    sbp = float(event.get("systolicBP",    120))
    bat = float(event.get("batteryLevel",  100))
    tx  = event.get("transmissionStatus", "").lower()
    syn = event.get("syncStatus",         "").lower()
    return (
        hr < HR_LOW or hr > HR_HIGH or
        spo < SPO2_LOW or
        sbp > SBP_HIGH or
        bat < BATTERY_LOW or
        tx == "failed" or
        syn == "failed"
    )


def _score_vitals_trend(events: list) -> float:
    """
    Score the trend in vitals over time.
    Uses the last 5 vs previous 5 events.
    Higher score = worsening trend.
    """
    if len(events) < 6:
        return 0.0

    recent   = events[:5]
    previous = events[5:10]

    recent_hr   = _avg(recent,   "heartRate")
    previous_hr = _avg(previous, "heartRate")
    recent_spo2 = _avg(recent,   "spo2")
    previous_spo2 = _avg(previous, "spo2")
    recent_sbp  = _avg(recent,   "systolicBP")
    previous_sbp = _avg(previous,"systolicBP")

    score = 0.0

    # HR worsening: moving away from 60–100 normal range
    hr_delta = abs(recent_hr - 75) - abs(previous_hr - 75)
    if hr_delta > 0:
        score += min(40, hr_delta * 2)

    # SpO2 worsening: falling
    spo2_delta = previous_spo2 - recent_spo2
    if spo2_delta > 0:
        score += min(40, spo2_delta * 5)

    # SBP worsening: rising above 140
    sbp_delta = recent_sbp - previous_sbp
    if sbp_delta > 0 and recent_sbp > 140:
        score += min(20, sbp_delta)

    return min(100, score)


def _score_device_health(events: list) -> float:
    """Score device health based on battery and signal strength."""
    if not events:
        return 0.0

    bat_vals = [float(e.get("batteryLevel",  100)) for e in events]
    sig_vals = [float(e.get("signalStrength", -60)) for e in events]

    avg_bat = sum(bat_vals) / len(bat_vals)
    avg_sig = sum(sig_vals) / len(sig_vals)

    # Battery score: 0–50 based on level
    if avg_bat >= 50:
        bat_score = 0
    elif avg_bat >= 20:
        bat_score = (50 - avg_bat) / 30 * 50
    else:
        bat_score = 50 + (20 - avg_bat) / 20 * 50

    # Signal score: 0–50 based on strength (dBm, more negative = worse)
    if avg_sig >= -70:
        sig_score = 0
    elif avg_sig >= -90:
        sig_score = (-70 - avg_sig) / 20 * 30
    else:
        sig_score = 30 + (-90 - avg_sig) / 30 * 20

    return min(100, bat_score + sig_score)


def _trend_direction(
    events: list, field: str, window: int, invert: bool = False
) -> str:
    """Return 'improving', 'stable', or 'worsening' for a field's trend."""
    if len(events) < window * 2:
        return "stable"
    recent   = _avg(events[:window],        field)
    previous = _avg(events[window:window*2], field)
    delta    = recent - previous
    if invert:
        delta = -delta
    if delta > 2:
        return "worsening"
    if delta < -2:
        return "improving"
    return "stable"


def _avg(events: list, field: str) -> float:
    vals = [float(e[field]) for e in events if field in e]
    return sum(vals) / len(vals) if vals else 0.0


def _risk_level(score: float) -> tuple[str, str]:
    if score < 25:
        return "LOW",      "#22c55e"
    if score < 50:
        return "MEDIUM",   "#f59e0b"
    if score < 75:
        return "HIGH",     "#f97316"
    return "CRITICAL",     "#ef4444"


def _build_factors(
    abnormal_rate: float, f_abnormal: float,
    tx_fail_rate: float,  f_tx: float,
    avg_spo2: float,      f_spo2: float,
    f_vitals: float,      f_device: float,
) -> list[dict]:
    """Build a human-readable list of contributing risk factors."""
    factors = []

    if f_abnormal >= 20:
        factors.append({
            "factor":      "Abnormal Event Frequency",
            "contribution": round(f_abnormal, 1),
            "detail":      f"{round(abnormal_rate * 100, 1)}% of recent events are abnormal",
            "severity":    "high" if f_abnormal >= 50 else "medium",
        })
    if f_tx >= 20:
        factors.append({
            "factor":      "Transmission Failures",
            "contribution": round(f_tx, 1),
            "detail":      f"{round(tx_fail_rate * 100, 1)}% transmission failure rate",
            "severity":    "high" if f_tx >= 50 else "medium",
        })
    if f_spo2 >= 20:
        factors.append({
            "factor":      "Low SpO2",
            "contribution": round(f_spo2, 1),
            "detail":      f"Average SpO2 {round(avg_spo2, 1)}% (normal ≥95%)",
            "severity":    "critical" if avg_spo2 < SPO2_CRITICAL else "high",
        })
    if f_vitals >= 20:
        factors.append({
            "factor":      "Worsening Vitals Trend",
            "contribution": round(f_vitals, 1),
            "detail":      "Vitals are trending away from normal range",
            "severity":    "medium",
        })
    if f_device >= 20:
        factors.append({
            "factor":      "Device Health",
            "contribution": round(f_device, 1),
            "detail":      "Battery or signal strength below optimal levels",
            "severity":    "medium",
        })

    return sorted(factors, key=lambda x: x["contribution"], reverse=True)


def _build_recommendations(level: str, factors: list, latest: dict) -> list[str]:
    """Generate clinical recommendations based on risk level and factors."""
    recs = []

    if level == "CRITICAL":
        recs.append("Immediate clinical review required — contact patient or next of kin.")
        recs.append("Consider escalating to emergency services if patient is unreachable.")
    elif level == "HIGH":
        recs.append("Schedule urgent clinical review within 2–4 hours.")
        recs.append("Review recent vital sign trends and compare with baseline.")

    factor_names = [f["factor"] for f in factors]

    if "Low SpO2" in factor_names:
        recs.append("Assess respiratory status — consider pulse oximetry verification.")
    if "Abnormal Event Frequency" in factor_names:
        recs.append("Review medication compliance and recent activity levels.")
    if "Transmission Failures" in factor_names:
        recs.append("Contact patient to verify device connectivity and placement.")
    if "Device Health" in factor_names:
        recs.append("Arrange device battery replacement or charging session.")
    if "Worsening Vitals Trend" in factor_names:
        recs.append("Compare current readings against patient's established baseline.")

    if level == "LOW" and not recs:
        recs.append("Patient vitals within normal range — continue routine monitoring.")

    return recs


def _empty_risk(patient_id: str) -> dict:
    return {
        "patientId":       patient_id,
        "riskScore":       0,
        "riskLevel":       "UNKNOWN",
        "riskColor":       "#94a3b8",
        "eventsAnalysed":  0,
        "factors":         [],
        "recommendations": ["No telemetry data available — verify device connectivity."],
        "latestVitals":    {},
    }
