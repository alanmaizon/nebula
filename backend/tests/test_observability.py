import logging
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.observability import sanitize_for_logging


def test_request_id_header_is_generated_when_missing() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    UUID(request_id)


def test_request_id_header_is_preserved_when_provided() -> None:
    with TestClient(app) as client:
        response = client.get("/ready", headers={"X-Request-ID": "demo-request-123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "demo-request-123"


def test_request_started_log_redacts_sensitive_query_values(caplog) -> None:
    with TestClient(app) as client:
        with caplog.at_level(logging.INFO, logger="nebula.api"):
            response = client.get("/health?token=supersecret&email=user@example.org&q=public")
    assert response.status_code == 200

    request_started_logs = [
        record for record in caplog.records if getattr(record, "event", None) == "request_started"
    ]
    assert request_started_logs
    query = request_started_logs[-1].query
    assert query["token"] == "[REDACTED]"
    assert query["email"] == "[REDACTED]"
    assert query["q"] == "public"


def test_sanitize_for_logging_redacts_common_sensitive_patterns() -> None:
    aws_access_key = "AKIA" "ABCDEFGHIJKLMNOP"
    aws_access_key_alt = "ASIA" "ABCDEFGHIJKLMNOP"
    payload = {
        "notes": (
            "Contact user@example.org or +1 (415) 555-0101, "
            "SSN 123-45-6789, token Bearer abc123, "
            f"keys {aws_access_key} and {aws_access_key_alt}, "
            "aws_secret_access_key=abcd1234abcd1234abcd1234abcd1234abcd1234, "
            f"aws_access_key_id={aws_access_key}, "
            "aws_session_token=IQoJb3JpZ2luX2VjEJf//////////wEaCXVzLWVhc3QtMSJHMEUCIBTESTTOKEN12345, "
            "x-amz-security-token: FQoGZXIvYXdzEJr//////////wEaDGV1LXdlc3QtMSJIMEYCIQCiTESTTOKEN67890."
        ),
        "api_key": "plain-value",
    }

    sanitized = sanitize_for_logging(payload, max_string_length=2000)
    notes = sanitized["notes"]
    assert "user@example.org" not in notes
    assert "415" not in notes
    assert "123-45-6789" not in notes
    assert "[REDACTED_EMAIL]" in notes
    assert "[REDACTED_PHONE]" in notes
    assert "[REDACTED_SSN]" in notes
    assert "Bearer [REDACTED]" in notes
    assert "[REDACTED_AWS_ACCESS_KEY]" in notes
    assert "aws_secret_access_key=[REDACTED]" in notes
    assert "aws_access_key_id=[REDACTED_AWS_ACCESS_KEY]" in notes
    assert "aws_session_token=[REDACTED]" in notes
    assert "x-amz-security-token: [REDACTED]" in notes
    assert sanitized["api_key"] == "[REDACTED]"


def test_sanitize_for_logging_redacts_sensitive_aws_header_keys() -> None:
    aws_access_key = "AKIA" "ABCDEFGHIJKLMNOP"
    payload = {
        "x-amz-security-token": "FQoGZXIvYXdzEJr//////////wEaDGV1LXdlc3QtMSJIMEYCIQCiTESTTOKEN67890",
        "x-amz-credential": f"{aws_access_key}/20260211/us-east-1/bedrock/aws4_request",
        "x-amz-signature": "deadbeefcafebabe",
        "x-amz-date": "20260211T000000Z",
    }
    sanitized = sanitize_for_logging(payload)
    assert sanitized["x-amz-security-token"] == "[REDACTED]"
    assert sanitized["x-amz-credential"] == "[REDACTED]"
    assert sanitized["x-amz-signature"] == "[REDACTED]"
    assert sanitized["x-amz-date"] == "20260211T000000Z"
