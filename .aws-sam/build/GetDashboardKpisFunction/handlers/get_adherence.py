"""
src/handlers/get_adherence.py
───────────────────────────────
Lambda handler for GET /dashboard/adherence

Returns per-patient adherence scores for the Patient Adherence bar chart:

[
  {"patientId": "P001", "adherence": 90},
  {"patientId": "P002", "adherence": 85},
  ...
]

Sorted by patientId ascending.
"""

import logging
import os

from services.dynamodb_service import get_all_patient_summaries
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/adherence"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/adherence")

    try:
        summaries = get_all_patient_summaries()

        adherence_data = sorted(
            [
                {
                    "patientId":  s["patientId"],
                    "adherence":  float(s.get("adherenceScore", 0)),
                    "totalEvents": int(s.get("totalEvents", 0)),
                }
                for s in summaries
                if "patientId" in s
            ],
            key=lambda x: x["patientId"],
        )

        return success({
            "patients":     adherence_data,
            "patientCount": len(adherence_data),
            "avgAdherence": round(
                sum(p["adherence"] for p in adherence_data) / len(adherence_data), 1
            ) if adherence_data else 0.0,
        })

    except Exception as exc:
        logger.error("GET /dashboard/adherence failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve adherence data.")
