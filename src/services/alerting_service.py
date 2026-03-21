"""
src/services/alerting_service.py
─────────────────────────────────
Real-time clinical alert notifications via Amazon SNS.

When the ingest Lambda detects an abnormal cardiac event it calls
publish_alert() which sends a structured notification to the
ClinicalAlerts SNS topic. The topic delivers an email to all
subscribed clinician addresses.

Free tier: 1M SNS publishes/month + 1000 email notifications/month.
"""

import os
import json
import logging
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)

ALERTS_TOPIC_ARN     = os.environ.get("ALERTS_TOPIC_ARN", "")
CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "RhythmCloud")

_sns = boto3.client("sns")
_cw  = boto3.client("cloudwatch")


def _classify_alert(event: dict) -> dict:
    """
    Determine the alert type, severity, and clinical message
    from the event data.

    Returns a dict with keys: type, severity, message
    """
    hr  = float(event.get("heartRate",      75))
    spo = float(event.get("spo2",           99))
    sbp = float(event.get("systolicBP",    120))
    bat = float(event.get("batteryLevel",  100))
    tx  = event.get("transmissionStatus", "").lower()
    syn = event.get("syncStatus", "").lower()

    if hr > 130:
        return {
            "type":     "TACHYCARDIA",
            "severity": "HIGH",
            "message":  f"Heart rate critically elevated at {hr:.0f} bpm (threshold: 130 bpm).",
        }
    if hr < 50:
        return {
            "type":     "BRADYCARDIA",
            "severity": "HIGH",
            "message":  f"Heart rate critically low at {hr:.0f} bpm (threshold: 50 bpm).",
        }
    if spo < 90:
        return {
            "type":     "HYPOXIA",
            "severity": "CRITICAL",
            "message":  f"SpO2 critically low at {spo:.1f}% (threshold: 90%).",
        }
    if sbp > 180:
        return {
            "type":     "HYPERTENSIVE_CRISIS",
            "severity": "CRITICAL",
            "message":  f"Systolic BP critically elevated at {sbp:.0f} mmHg (threshold: 180 mmHg).",
        }
    if bat < 20:
        return {
            "type":     "BATTERY_CRITICAL",
            "severity": "MEDIUM",
            "message":  f"Device battery critically low at {bat:.0f}% — replacement required soon.",
        }
    if tx == "failed":
        return {
            "type":     "TRANSMISSION_FAILURE",
            "severity": "MEDIUM",
            "message":  "Device transmission failed — patient data may be delayed.",
        }
    if syn == "failed":
        return {
            "type":     "SYNC_FAILURE",
            "severity": "LOW",
            "message":  "Device sync failed — last sync status unknown.",
        }

    return {
        "type":     "ABNORMAL_EVENT",
        "severity": "MEDIUM",
        "message":  "Abnormal clinical indicators detected.",
    }


def _format_email(event: dict, alert: dict) -> dict:
    """
    Format the SNS subject and message body for the alert email.

    Returns dict with 'subject' and 'message' keys.
    """
    patient_id = event.get("patientId",  "UNKNOWN")
    device_id  = event.get("deviceId",   "UNKNOWN")
    timestamp  = event.get("timestamp",  "UNKNOWN")
    hr         = event.get("heartRate",  "N/A")
    spo        = event.get("spo2",       "N/A")
    sbp        = event.get("systolicBP", "N/A")
    dbp        = event.get("diastolicBP","N/A")
    bat        = event.get("batteryLevel","N/A")
    tx         = event.get("transmissionStatus","N/A")
    sync       = event.get("syncStatus", "N/A")

    severity = alert["severity"]
    alert_type = alert["type"].replace("_", " ").title()

    subject = f"[{severity}] RhythmCloud Alert — {alert_type} — Patient {patient_id}"

    message = f"""
RhythmCloud Clinical Alert
══════════════════════════════════════════

ALERT TYPE : {alert_type}
SEVERITY   : {severity}
PATIENT ID : {patient_id}
DEVICE ID  : {device_id}
TIMESTAMP  : {timestamp}

CLINICAL SUMMARY
─────────────────
{alert['message']}

VITALS AT TIME OF ALERT
────────────────────────
Heart Rate      : {hr} bpm
SpO2            : {spo} %
Systolic BP     : {sbp} mmHg
Diastolic BP    : {dbp} mmHg
Battery Level   : {bat} %
TX Status       : {tx}
Sync Status     : {sync}

ACTION REQUIRED
────────────────
Please review patient {patient_id}'s status and take appropriate
clinical action based on the severity of this alert.

──────────────────────────────────────────
RhythmCloud — Cloud-Based Remote Patient Monitoring Platform
This is an automated alert. Do not reply to this email.
Alert generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
"""

    return {"subject": subject, "message": message}


def publish_alert(event: dict) -> bool:
    """
    Publish a clinical alert to the SNS topic.

    Called by the ingest Lambda when is_abnormal_event() returns True.

    Args:
        event: The full telemetry event dict (already validated).

    Returns:
        True if the alert was published, False if SNS is not configured
        or the publish failed.
    """
    if not ALERTS_TOPIC_ARN:
        logger.warning("ALERTS_TOPIC_ARN not set — skipping alert publish")
        return False

    try:
        alert      = _classify_alert(event)
        formatted  = _format_email(event, alert)

        response = _sns.publish(
            TopicArn = ALERTS_TOPIC_ARN,
            Subject  = formatted["subject"][:100],  # SNS subject max 100 chars
            Message  = formatted["message"],
            MessageAttributes={
                "alertType": {
                    "DataType":    "String",
                    "StringValue": alert["type"],
                },
                "severity": {
                    "DataType":    "String",
                    "StringValue": alert["severity"],
                },
                "patientId": {
                    "DataType":    "String",
                    "StringValue": event.get("patientId", "UNKNOWN"),
                },
            },
        )

        message_id = response.get("MessageId", "unknown")
        logger.info(
            "Alert published | messageId=%s patientId=%s type=%s severity=%s",
            message_id,
            event.get("patientId"),
            alert["type"],
            alert["severity"],
        )

        # ── Write alert record to DynamoDB for response time tracking ─────────
        try:
            from services.alerts_db_service import put_alert
            from decimal import Decimal
            alert_record = {
                "alertId":    str(uuid.uuid4()),
                "patientId":  event.get("patientId", "UNKNOWN"),
                "deviceId":   event.get("deviceId",  "UNKNOWN"),
                "eventId":    event.get("eventId",   "UNKNOWN"),
                "alertType":  alert["type"],
                "severity":   alert["severity"],
                "message":    alert["message"],
                "status":     "ACTIVE",
                "detectedAt": event.get("ingestedAt",
                              datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                "snsMessageId":      message_id,
                "heartRate":         Decimal(str(event.get("heartRate",      0))),
                "spo2":              Decimal(str(event.get("spo2",           0))),
                "systolicBP":        Decimal(str(event.get("systolicBP",     0))),
                "transmissionStatus":event.get("transmissionStatus", ""),
                "syncStatus":        event.get("syncStatus",     ""),
            }
            put_alert(alert_record)
        except Exception as db_exc:
            logger.warning("Failed to write alert record to DynamoDB: %s", db_exc)

        # Publish AlertsSent metric to CloudWatch
        try:
            _cw.put_metric_data(
                Namespace  = CLOUDWATCH_NAMESPACE,
                MetricData = [{
                    "MetricName": "AlertsSent",
                    "Value":      1,
                    "Unit":       "Count",
                    "Dimensions": [
                        {"Name": "Severity", "Value": alert["severity"]},
                        {"Name": "AlertType","Value": alert["type"]},
                    ],
                }],
            )
        except Exception as cw_exc:
            logger.warning("CloudWatch metric publish failed: %s", cw_exc)

        return True

    except Exception as exc:
        logger.error("SNS alert publish failed: %s", exc, exc_info=True)
        return False
