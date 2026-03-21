"""
src/handlers/get_patient_summary.py
─────────────────────────────────────
Lambda handler for GET /patients/{patientId}/summary

Returns the full KPI summary for a single patient:
  - transmission success rate
  - sync reliability
  - adherence score
  - abnormal event frequency
  - average vitals
  - latest device status
"""

import logging
import os

from services.dynamodb_service import get_patient_summary
from utils.response import success, not_found, bad_request, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /patients/{patientId}/summary"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    # Extract patientId from path parameters
    path_params = event.get("pathParameters") or {}
    patient_id  = path_params.get("patientId", "").strip()

    if not patient_id:
        return bad_request("Path parameter 'patientId' is required.")

    logger.info("GET /patients/%s/summary", patient_id)

    try:
        summary = get_patient_summary(patient_id)

        if summary is None:
            return not_found("Patient", patient_id)

        return success(summary)

    except Exception as exc:
        logger.error(
            "GET /patients/%s/summary failed: %s", patient_id, exc, exc_info=True
        )
        return internal_error("Failed to retrieve patient summary.")
