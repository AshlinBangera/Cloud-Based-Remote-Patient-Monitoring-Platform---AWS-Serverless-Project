"""
src/handlers/get_dashboard_kpis.py
────────────────────────────────────
Lambda handler for GET /dashboard/kpis

Returns the top-level KPI payload that drives the dashboard:
  - Transmission success rate gauge
  - Device sync reliability card
  - Abnormal event counter
  - Adherence score
  - Transmission / sync failure counts

Data source: latest 'dashboard-kpis' aggregate from DashboardAggregatesTable.
Falls back to live computation from PatientSummaries if no aggregate exists yet.
"""

import logging
import os

from services.dynamodb_service import get_aggregates, get_all_patient_summaries
from services.aggregation_service import compute_dashboard_kpis
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/kpis"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/kpis")

    try:
        # Try the pre-computed aggregate first (fastest path)
        aggregates = get_aggregates("dashboard-kpis", limit=1)

        if aggregates:
            kpis = aggregates[0]["data"]
            logger.info("Returning cached dashboard KPIs")
        else:
            # Fall back to live computation across all patient summaries
            logger.info("No cached KPIs — computing live from patient summaries")
            all_summaries = get_all_patient_summaries()
            kpis = compute_dashboard_kpis(all_summaries)

        return success(kpis)

    except Exception as exc:
        logger.error("GET /dashboard/kpis failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve dashboard KPIs.")
