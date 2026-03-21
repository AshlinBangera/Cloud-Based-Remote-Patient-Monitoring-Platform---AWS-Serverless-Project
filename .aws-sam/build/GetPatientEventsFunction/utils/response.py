"""
src/utils/response.py
─────────────────────
Standardised HTTP response builders for API Gateway Lambda proxy integration.
All responses include CORS headers so the dashboard can call the API
from any origin.
"""

import json
from typing import Any

# CORS headers returned on every response
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type":                 "application/json",
}


def _build(status_code: int, body: Any) -> dict:
    """Build a Lambda proxy integration response dict."""
    return {
        "statusCode": status_code,
        "headers":    _CORS_HEADERS,
        "body":       json.dumps(body, default=str),
    }


def success(body: Any, status_code: int = 200) -> dict:
    """200 OK (or any 2xx) response."""
    return _build(status_code, body)


def created(body: Any) -> dict:
    """201 Created response."""
    return _build(201, body)


def bad_request(message: str, field: str | None = None) -> dict:
    """400 Bad Request – validation failures."""
    payload: dict = {"error": "BadRequest", "message": message}
    if field:
        payload["field"] = field
    return _build(400, payload)


def not_found(resource: str, identifier: str) -> dict:
    """404 Not Found."""
    return _build(404, {
        "error":   "NotFound",
        "message": f"{resource} '{identifier}' not found.",
    })


def internal_error(message: str = "An internal error occurred.") -> dict:
    """500 Internal Server Error."""
    return _build(500, {
        "error":   "InternalServerError",
        "message": message,
    })


def options_response() -> dict:
    """200 response for CORS preflight OPTIONS requests."""
    return _build(200, {"message": "OK"})
