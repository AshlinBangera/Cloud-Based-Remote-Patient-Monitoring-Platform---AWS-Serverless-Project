"""
src/utils/validator.py
─────────────────────
Schema validation for incoming cardiac telemetry event payloads.
Validates presence, type, range, and enum constraints before
any data is written to DynamoDB or S3.
"""

import re
from typing import Any

# ── Required fields and their expected Python types ───────────────────────────
REQUIRED_FIELDS: dict[str, type | tuple] = {
    "patientId":          str,
    "deviceId":           str,
    "timestamp":          str,
    "heartRate":          (int, float),
    "spo2":               (int, float),
    "systolicBP":         (int, float),
    "diastolicBP":        (int, float),
    "batteryLevel":       (int, float),
    "signalStrength":     (int, float),
    "transmissionStatus": str,
    "syncStatus":         str,
    "eventType":          str,
}

# ── Allowed enum values ────────────────────────────────────────────────────────
VALID_TRANSMISSION_STATUSES = {"success", "failed", "pending"}
VALID_SYNC_STATUSES          = {"synced", "failed", "pending"}
VALID_EVENT_TYPES            = {"vitals", "alert", "device_health", "sync", "battery"}

# ── Physiological plausibility bounds ─────────────────────────────────────────
NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "heartRate":      (20.0,   300.0),
    "spo2":           (50.0,   100.0),
    "systolicBP":     (60.0,   250.0),
    "diastolicBP":    (30.0,   160.0),
    "batteryLevel":   (0.0,    100.0),
    "signalStrength": (-130.0,   0.0),
}

# ISO 8601 timestamp pattern
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


class ValidationError(Exception):
    """Raised when an event payload fails validation."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field   = field

    def to_dict(self) -> dict:
        return {
            "error":   "ValidationError",
            "message": self.message,
            "field":   self.field,
        }


def validate_event(payload: Any) -> dict:
    """
    Validate a telemetry event payload.

    Args:
        payload: Parsed JSON body from the API request.

    Returns:
        The validated payload dict (unchanged).

    Raises:
        ValidationError: On any field violation.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be a JSON object.", field=None)

    # 1. Required field presence and type ─────────────────────────────────────
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in payload:
            raise ValidationError(
                f"Missing required field: '{field}'.", field=field
            )
        value = payload[field]
        if not isinstance(value, expected_type):
            if isinstance(expected_type, tuple):
                type_name = " or ".join(t.__name__ for t in expected_type)
            else:
                type_name = expected_type.__name__
            raise ValidationError(
                f"Field '{field}' must be {type_name}, "
                f"got {type(value).__name__}.",
                field=field,
            )

    # 2. Non-empty string checks ───────────────────────────────────────────────
    for field in ("patientId", "deviceId", "eventType",
                  "transmissionStatus", "syncStatus"):
        if not payload[field].strip():
            raise ValidationError(
                f"Field '{field}' must not be empty.", field=field
            )

    # 3. Timestamp format ──────────────────────────────────────────────────────
    if not _ISO8601_RE.match(payload["timestamp"]):
        raise ValidationError(
            "Field 'timestamp' must be ISO 8601 "
            "(e.g. 2026-03-20T14:32:00Z).",
            field="timestamp",
        )

    # 4. Enum validation ───────────────────────────────────────────────────────
    ts = payload["transmissionStatus"].lower()
    if ts not in VALID_TRANSMISSION_STATUSES:
        raise ValidationError(
            f"'transmissionStatus' must be one of "
            f"{sorted(VALID_TRANSMISSION_STATUSES)}, got '{ts}'.",
            field="transmissionStatus",
        )

    ss = payload["syncStatus"].lower()
    if ss not in VALID_SYNC_STATUSES:
        raise ValidationError(
            f"'syncStatus' must be one of "
            f"{sorted(VALID_SYNC_STATUSES)}, got '{ss}'.",
            field="syncStatus",
        )

    et = payload["eventType"].lower()
    if et not in VALID_EVENT_TYPES:
        raise ValidationError(
            f"'eventType' must be one of "
            f"{sorted(VALID_EVENT_TYPES)}, got '{et}'.",
            field="eventType",
        )

    # 5. Numeric bounds ────────────────────────────────────────────────────────
    for field, (lo, hi) in NUMERIC_BOUNDS.items():
        val = float(payload[field])
        if not (lo <= val <= hi):
            raise ValidationError(
                f"Field '{field}' value {val} is outside "
                f"acceptable range [{lo}, {hi}].",
                field=field,
            )

    # 6. patientId / deviceId length ───────────────────────────────────────────
    if len(payload["patientId"]) > 64:
        raise ValidationError(
            "'patientId' must be 64 characters or fewer.",
            field="patientId",
        )
    if len(payload["deviceId"]) > 64:
        raise ValidationError(
            "'deviceId' must be 64 characters or fewer.",
            field="deviceId",
        )

    return payload
