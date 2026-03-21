"""
src/handlers/get_patient_risk.py
──────────────────────────────────
Lambda handler for GET /patients/{patientId}/risk

Reads the last 50 telemetry events for a patient, runs them through
the risk scoring engine, and returns a full risk assessment.

Response (200):
  {
    "patientId":      "P001",
    "riskScore":      67.4,
    "riskLevel":      "HIGH",
    "riskColor":      "#f97316",
    "eventsAnalysed": 50,
    "abnormalCount":  12,
    "abnormalRate":   24.0,
    "avgSpo2":        91.3,
    "avgHeartRate":   102.1,
    "txFailureRate":  8.0,
    "heartRateTrend": "worsening",
    "spo2Trend":      "stable",
    "scoreBreakdown": { ... },
    "factors":        [ ... ],
    "recommendations":[ ... ],
    "latestVitals":   { ... }
  }
"""

import logging
import os

import boto3

from services.dynamodb_service    import get_patient_events
from services.risk_scoring_service import compute_risk_score
from utils.response import success, not_found, bad_request, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "RhythmCloud")
_cw = boto3.client("cloudwatch")

_EVENTS_FOR_SCORING = 50


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /patients/{patientId}/risk"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    path_params = event.get("pathParameters") or {}
    patient_id  = path_params.get("patientId", "").strip()

    if not patient_id:
        return bad_request("Path parameter 'patientId' is required.")

    logger.info("GET /patients/%s/risk", patient_id)

    try:
        # Fetch last 50 events for scoring
        result = get_patient_events(
            patient_id = patient_id,
            limit      = _EVENTS_FOR_SCORING,
        )
        events = result.get("items", [])

        if not events:
            return not_found("Patient", patient_id)

        # Compute risk score
        risk = compute_risk_score(patient_id, events)

        # Publish risk score to CloudWatch
        try:
            _cw.put_metric_data(
                Namespace  = CLOUDWATCH_NAMESPACE,
                MetricData = [
                    {
                        "MetricName": "PatientRiskScore",
                        "Value":      float(risk["riskScore"]),
                        "Unit":       "None",
                        "Dimensions": [
                            {"Name": "PatientId", "Value": patient_id},
                            {"Name": "RiskLevel",  "Value": risk["riskLevel"]},
                        ],
                    },
                    {
                        "MetricName": "HighRiskPatients",
                        "Value":      1 if risk["riskLevel"] in ("HIGH", "CRITICAL") else 0,
                        "Unit":       "Count",
                    },
                ],
            )
        except Exception as cw_exc:
            logger.warning("CloudWatch metric publish failed: %s", cw_exc)

        logger.info(
            "Risk score computed | patientId=%s score=%.1f level=%s",
            patient_id, risk["riskScore"], risk["riskLevel"]
        )

        return success(risk)

    except Exception as exc:
        logger.error(
            "GET /patients/%s/risk failed: %s", patient_id, exc, exc_info=True
        )
        return internal_error("Failed to compute patient risk score.")
