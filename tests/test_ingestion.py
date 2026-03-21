"""
tests/test_ingestion.py
────────────────────────
Unit tests for the ingest_event Lambda handler.
All AWS calls are mocked using moto — no real AWS resources needed.
"""

import json
import os
import pytest
import boto3
from moto import mock_aws

# ── Environment variables required by the handlers ────────────────────────────
os.environ.setdefault("EVENTS_TABLE",        "rhythmcloud-telemetry-events-dev")
os.environ.setdefault("SUMMARIES_TABLE",     "rhythmcloud-patient-summaries-dev")
os.environ.setdefault("AGGREGATES_TABLE",    "rhythmcloud-dashboard-aggregates-dev")
os.environ.setdefault("RECENT_EVENTS_TABLE", "rhythmcloud-recent-events-dev")
os.environ.setdefault("DEVICE_STATUS_TABLE", "rhythmcloud-device-status-dev")
os.environ.setdefault("RAW_EVENTS_BUCKET",   "rhythmcloud-raw-events-test-dev")
os.environ.setdefault("CLOUDWATCH_NAMESPACE","RhythmCloud")
os.environ.setdefault("ENVIRONMENT",         "test")
os.environ.setdefault("LOG_LEVEL",           "DEBUG")
os.environ.setdefault("AWS_DEFAULT_REGION",  "eu-north-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID",   "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY","testing")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_event_body():
    return {
        "patientId":          "P001",
        "deviceId":           "D-P001-001AB",
        "timestamp":          "2026-03-21T14:32:00Z",
        "heartRate":          87,
        "spo2":               97.5,
        "systolicBP":         122,
        "diastolicBP":        80,
        "batteryLevel":       74,
        "signalStrength":     -68,
        "transmissionStatus": "success",
        "syncStatus":         "synced",
        "eventType":          "vitals",
    }


@pytest.fixture
def abnormal_event_body():
    return {
        "patientId":          "P002",
        "deviceId":           "D-P002-002CD",
        "timestamp":          "2026-03-21T14:35:00Z",
        "heartRate":          148,
        "spo2":               88.0,
        "systolicBP":         165,
        "diastolicBP":        105,
        "batteryLevel":       12,
        "signalStrength":     -95,
        "transmissionStatus": "failed",
        "syncStatus":         "failed",
        "eventType":          "alert",
    }


def api_gateway_event(body: dict, method: str = "POST") -> dict:
    """Wrap a body dict in an API Gateway proxy event."""
    return {
        "httpMethod":      method,
        "body":            json.dumps(body),
        "pathParameters":  {},
        "queryStringParameters": {},
        "requestContext":  {"requestId": "test-request-001"},
        "isBase64Encoded": False,
    }


def create_aws_resources():
    """Create all required DynamoDB tables and S3 bucket for tests."""
    dynamodb = boto3.resource("dynamodb", region_name="eu-north-1")

    # TelemetryEvents
    dynamodb.create_table(
        TableName=os.environ["EVENTS_TABLE"],
        KeySchema=[
            {"AttributeName": "patientId", "KeyType": "HASH"},
            {"AttributeName": "eventId",   "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "patientId", "AttributeType": "S"},
            {"AttributeName": "eventId",   "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "PatientTimestampIndex",
            "KeySchema": [
                {"AttributeName": "patientId",  "KeyType": "HASH"},
                {"AttributeName": "timestamp",  "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )

    # PatientSummaries
    dynamodb.create_table(
        TableName=os.environ["SUMMARIES_TABLE"],
        KeySchema=[{"AttributeName": "patientId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "patientId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # DashboardAggregates
    dynamodb.create_table(
        TableName=os.environ["AGGREGATES_TABLE"],
        KeySchema=[
            {"AttributeName": "metricType", "KeyType": "HASH"},
            {"AttributeName": "periodKey",  "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "metricType", "AttributeType": "S"},
            {"AttributeName": "periodKey",  "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # RecentEvents
    dynamodb.create_table(
        TableName=os.environ["RECENT_EVENTS_TABLE"],
        KeySchema=[
            {"AttributeName": "partitionKey", "KeyType": "HASH"},
            {"AttributeName": "sortKey",      "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "partitionKey", "AttributeType": "S"},
            {"AttributeName": "sortKey",      "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # DeviceStatus
    dynamodb.create_table(
        TableName=os.environ["DEVICE_STATUS_TABLE"],
        KeySchema=[{"AttributeName": "deviceId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "deviceId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # S3 bucket
    s3 = boto3.client("s3", region_name="eu-north-1")
    s3.create_bucket(
        Bucket=os.environ["RAW_EVENTS_BUCKET"],
        CreateBucketConfiguration={"LocationConstraint": "eu-north-1"},
    )


# ── Tests: Validator ──────────────────────────────────────────────────────────

class TestValidator:

    def test_valid_event_passes(self, valid_event_body):
        from utils.validator import validate_event
        result = validate_event(valid_event_body)
        assert result["patientId"] == "P001"

    def test_missing_field_raises(self, valid_event_body):
        from utils.validator import validate_event, ValidationError
        del valid_event_body["heartRate"]
        with pytest.raises(ValidationError) as exc:
            validate_event(valid_event_body)
        assert "heartRate" in exc.value.message

    def test_heart_rate_out_of_range(self, valid_event_body):
        from utils.validator import validate_event, ValidationError
        valid_event_body["heartRate"] = 350
        with pytest.raises(ValidationError) as exc:
            validate_event(valid_event_body)
        assert "heartRate" in exc.value.message

    def test_invalid_transmission_status(self, valid_event_body):
        from utils.validator import validate_event, ValidationError
        valid_event_body["transmissionStatus"] = "unknown"
        with pytest.raises(ValidationError):
            validate_event(valid_event_body)

    def test_invalid_timestamp_format(self, valid_event_body):
        from utils.validator import validate_event, ValidationError
        valid_event_body["timestamp"] = "21-03-2026"
        with pytest.raises(ValidationError) as exc:
            validate_event(valid_event_body)
        assert "timestamp" in exc.value.message

    def test_non_dict_payload_raises(self):
        from utils.validator import validate_event, ValidationError
        with pytest.raises(ValidationError):
            validate_event("not a dict")


# ── Tests: Aggregation ────────────────────────────────────────────────────────

class TestAggregation:

    def test_normal_event_not_abnormal(self, valid_event_body):
        from services.aggregation_service import is_abnormal_event
        assert is_abnormal_event(valid_event_body) is False

    def test_high_heart_rate_is_abnormal(self, valid_event_body):
        from services.aggregation_service import is_abnormal_event
        valid_event_body["heartRate"] = 145
        assert is_abnormal_event(valid_event_body) is True

    def test_low_spo2_is_abnormal(self, valid_event_body):
        from services.aggregation_service import is_abnormal_event
        valid_event_body["spo2"] = 85
        assert is_abnormal_event(valid_event_body) is True

    def test_failed_transmission_is_abnormal(self, valid_event_body):
        from services.aggregation_service import is_abnormal_event
        valid_event_body["transmissionStatus"] = "failed"
        assert is_abnormal_event(valid_event_body) is True

    def test_compute_summary_with_events(self, valid_event_body):
        from services.aggregation_service import compute_patient_summary
        events = [valid_event_body] * 5
        summary = compute_patient_summary("P001", events)
        assert summary["patientId"] == "P001"
        assert summary["totalEvents"] == 5
        assert summary["transmissionSuccessRate"] == 100.0
        assert summary["adherenceScore"] == 100.0

    def test_empty_events_returns_empty_summary(self):
        from services.aggregation_service import compute_patient_summary
        summary = compute_patient_summary("P001", [])
        assert summary["totalEvents"] == 0
        assert summary["transmissionSuccessRate"] == 0.0


# ── Tests: Ingest handler ─────────────────────────────────────────────────────

class TestIngestHandler:

    @mock_aws
    def test_valid_event_returns_201(self, valid_event_body):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        response = lambda_handler(api_gateway_event(valid_event_body), {})
        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "eventId" in body
        assert body["patientId"] == "P001"

    @mock_aws
    def test_missing_body_returns_400(self):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        event = {"httpMethod": "POST", "body": None}
        response = lambda_handler(event, {})
        assert response["statusCode"] == 400

    @mock_aws
    def test_invalid_json_returns_400(self):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        event = {"httpMethod": "POST", "body": "not json at all"}
        response = lambda_handler(event, {})
        assert response["statusCode"] == 400

    @mock_aws
    def test_validation_failure_returns_400(self, valid_event_body):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        valid_event_body["heartRate"] = 999
        response = lambda_handler(api_gateway_event(valid_event_body), {})
        assert response["statusCode"] == 400

    @mock_aws
    def test_options_returns_200(self):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        event = {"httpMethod": "OPTIONS", "body": None}
        response = lambda_handler(event, {})
        assert response["statusCode"] == 200

    @mock_aws
    def test_abnormal_event_ingested_successfully(self, abnormal_event_body):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        response = lambda_handler(api_gateway_event(abnormal_event_body), {})
        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert body["patientId"] == "P002"

    @mock_aws
    def test_response_includes_s3_key(self, valid_event_body):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        response = lambda_handler(api_gateway_event(valid_event_body), {})
        body = json.loads(response["body"])
        assert "s3Key" in body
        assert "events/year=" in body["s3Key"]

    @mock_aws
    def test_cors_headers_present(self, valid_event_body):
        create_aws_resources()
        from handlers.ingest_event import lambda_handler
        response = lambda_handler(api_gateway_event(valid_event_body), {})
        assert "Access-Control-Allow-Origin" in response["headers"]
