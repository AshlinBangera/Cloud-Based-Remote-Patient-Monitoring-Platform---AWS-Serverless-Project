"""
src/handlers/get_heatmap.py
─────────────────────────────
Lambda handler for GET /dashboard/heatmap

Returns cardiac event counts broken down by day-of-week and 3-hour time bucket,
formatted for the Cardiac Event Heatmap widget:

{
  "days":        ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
  "timeBuckets": ["00","03","06","09","12","15","18"],
  "matrix":      [[3,4,2,8,12,7,4], ...]   // 7 rows x 7 cols
}
"""

import logging
import os

from services.dynamodb_service import get_aggregates
from utils.time_buckets import DAYS_OF_WEEK, HEATMAP_BUCKETS
from utils.response import success, internal_error, options_response

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict, context) -> dict:
    """Entry point for GET /dashboard/heatmap"""

    if event.get("httpMethod") == "OPTIONS":
        return options_response()

    logger.info("GET /dashboard/heatmap")

    try:
        # Initialise a 7x7 zero matrix: rows=days, cols=time buckets
        # matrix[day_index][bucket_index]
        day_index    = {d: i for i, d in enumerate(DAYS_OF_WEEK)}
        bucket_index = {b: i for i, b in enumerate(HEATMAP_BUCKETS)}

        matrix = [[0] * len(HEATMAP_BUCKETS) for _ in DAYS_OF_WEEK]

        # Load heatmap aggregates (up to 500 cells)
        aggregates = get_aggregates("heatmap", limit=500)

        for agg in aggregates:
            data   = agg.get("data", {})
            day    = data.get("day",    "")
            bucket = data.get("bucket", "")
            count  = int(data.get("count", 0))

            di = day_index.get(day)
            bi = bucket_index.get(bucket)

            if di is not None and bi is not None:
                matrix[di][bi] += count

        return success({
            "days":        DAYS_OF_WEEK,
            "timeBuckets": HEATMAP_BUCKETS,
            "matrix":      matrix,
        })

    except Exception as exc:
        logger.error("GET /dashboard/heatmap failed: %s", exc, exc_info=True)
        return internal_error("Failed to retrieve heatmap data.")
