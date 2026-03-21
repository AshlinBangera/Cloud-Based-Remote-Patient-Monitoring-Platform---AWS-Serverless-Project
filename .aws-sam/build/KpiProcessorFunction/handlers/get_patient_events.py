"""
src/handlers/get_patient_events.py
────────────────────────────────────
Lambda handler for GET /patients/{patientId}/events

Returns paginated telemetry event history for a patient,
ordered newest first.

Query params:
  ?limit=50           Events per page (default 50, max 100)
  ?nextToken=<token>  Pagination cursor from previous response
  ?startTimestamp=    ISO 8601 range filter (inclusive)
  ?endTimestamp=      ISO 8601 range filter (inclusive)

Response:
{
  "patientId":    "P001",
  "events":       [...],
  "count":        50,
  "nextToken":    "<base64 cursor>" | null
}
"""

import base64
import json
import logging
import os

from services.dynamodb_service import get_patient_events
from utils.response import (
    success, not_found, bad_request, internal_error, options_response
)

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_DEFAULT_LIMIT = 50
_MAX_LIMIT      = 100


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /patients/{patientId}/events"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    # ── Path parameters ───────────────────────────────────────────────────────
    path_params = event.get("pathParameters") or {}
    patient_id  = path_params.get("patientId", "").strip()

    if not patient_id:
        return bad_request("Path parameter 'patientId' is required.")

    # ── Query parameters ──────────────────────────────────────────────────────
    params = event.get("queryStringParameters") or {}

    try:
        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except (ValueError, TypeError):
        limit = _DEFAULT_LIMIT

    # Decode pagination cursor
    last_evaluated_key = None
    next_token = params.get("nextToken")
    if next_token:
        try:
            last_evaluated_key = json.loads(
                base64.b64decode(next_token.encode()).decode()
            )
        except Exception:
            return bad_request("Invalid 'nextToken' cursor.")

    start_ts = params.get("startTimestamp")
    end_ts   = params.get("endTimestamp")

    logger.info(
        "GET /patients/%s/events limit=%d token=%s",
        patient_id, limit, bool(next_token)
    )

    try:
        result = get_patient_events(
            patient_id          = patient_id,
            limit               = limit,
            last_evaluated_key  = last_evaluated_key,
            start_timestamp     = start_ts,
            end_timestamp       = end_ts,
        )

        events = result["items"]

        # If no events and no cursor, the patient doesn't exist
        if not events and not next_token:
            # Check if patient has any data at all
            check = get_patient_events(patient_id, limit=1)
            if not check["items"]:
                return not_found("Patient", patient_id)

        # Encode next page cursor
        next_cursor = None
        if result.get("lastEvaluatedKey"):
            next_cursor = base64.b64encode(
                json.dumps(result["lastEvaluatedKey"]).encode()
            ).decode()

        return success({
            "patientId": patient_id,
            "events":    events,
            "count":     result["count"],
            "nextToken": next_cursor,
            "hasMore":   next_cursor is not None,
        })

    except Exception as exc:
        logger.error(
            "GET /patients/%s/events failed: %s", patient_id, exc, exc_info=True
        )
        return internal_error("Failed to retrieve patient events.")
