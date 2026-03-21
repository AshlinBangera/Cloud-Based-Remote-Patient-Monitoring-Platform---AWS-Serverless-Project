"""
src/services/metrics_service.py
────────────────────────────────
Publishes custom CloudWatch metrics for the RhythmCloud namespace.
Called by the KPI processor after each aggregation cycle.
"""

import os
import logging

import boto3

logger     = logging.getLogger(__name__)
NAMESPACE  = os.environ.get("CLOUDWATCH_NAMESPACE", "RhythmCloud")
_cw        = boto3.client("cloudwatch")


def _put(metric_name: str, value: float, unit: str = "Count") -> None:
    """Publish a single metric datum to CloudWatch."""
    try:
        _cw.put_metric_data(
            Namespace  = NAMESPACE,
            MetricData = [{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       unit,
            }],
        )
        logger.debug("Published metric %s = %s", metric_name, value)
    except Exception as exc:
        # Metric publishing failures should never crash the main flow
        logger.warning("Failed to publish metric %s: %s", metric_name, exc)


def publish_ingest_metrics(event: dict) -> None:
    """
    Publish per-event metrics immediately after ingestion.
    Called by the ingest handler.
    """
    _put("TotalEvents", 1)

    from services.aggregation_service import is_abnormal_event
    if is_abnormal_event(event):
        _put("AbnormalEvents", 1)

    if event.get("transmissionStatus", "").lower() == "failed":
        _put("TransmissionFailures", 1)

    if event.get("syncStatus", "").lower() == "failed":
        _put("SyncFailures", 1)


def publish_kpi_metrics(kpis: dict) -> None:
    """
    Publish aggregated KPI metrics after each KPI processing cycle.
    Called by the KPI processor handler.
    """
    tx_rate = kpis.get("transmissionSuccessRate", {})
    if isinstance(tx_rate, dict):
        _put("TransmissionSuccessRate", tx_rate.get("value", 0), unit="Percent")
    else:
        _put("TransmissionSuccessRate", float(tx_rate), unit="Percent")

    _put("AdherenceScore", float(kpis.get("adherenceScore", 0)), unit="Percent")
    _put("SyncFailures",         float(kpis.get("syncFailures", 0)))
    _put("TransmissionFailures", float(kpis.get("transmissionFailures", 0)))

    abnormal = kpis.get("abnormalEvents", {})
    if isinstance(abnormal, dict):
        _put("AbnormalEvents", float(abnormal.get("count24h", 0)))
