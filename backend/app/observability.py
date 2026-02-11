from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Mapping
from uuid import uuid4


REQUEST_ID_CONTEXT: ContextVar[str] = ContextVar("request_id", default="-")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOGGING_CONFIGURED = False

SENSITIVE_KEY_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "x_api_key",
    "access_key",
    "aws_secret_access_key",
    "aws_session_token",
    "session_token",
    "client_secret",
    "private_key",
    "ssn",
    "social_security_number",
    "email",
    "phone",
}
SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "access_key",
    "private_key",
)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b")
AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
AWS_SECRET_INLINE_PATTERN = re.compile(
    r"(?i)\b(aws_secret_access_key|secret_access_key)(\s*[:=]\s*)([A-Za-z0-9/+=]{16,})\b"
)


def normalize_request_id(candidate: str | None) -> str:
    if candidate:
        trimmed = candidate.strip()
        if REQUEST_ID_PATTERN.fullmatch(trimmed):
            return trimmed
    return str(uuid4())


def set_request_id(request_id: str) -> Token[str]:
    return REQUEST_ID_CONTEXT.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    REQUEST_ID_CONTEXT.reset(token)


def get_request_id() -> str:
    return REQUEST_ID_CONTEXT.get()


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in SENSITIVE_KEY_NAMES:
        return True
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _redact_string(value: str, *, max_length: int) -> str:
    redacted = value
    redacted = BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    redacted = AWS_ACCESS_KEY_PATTERN.sub("[REDACTED_AWS_ACCESS_KEY]", redacted)
    redacted = AWS_SECRET_INLINE_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
    redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    redacted = SSN_PATTERN.sub("[REDACTED_SSN]", redacted)
    if len(redacted) > max_length:
        return f"{redacted[:max_length]}...[truncated]"
    return redacted


def sanitize_for_logging(value: Any, *, max_string_length: int = 240) -> Any:
    if value is None:
        return None

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _looks_sensitive_key(key_text):
                sanitized[key_text] = "[REDACTED]"
                continue
            sanitized[key_text] = sanitize_for_logging(item, max_string_length=max_string_length)
        return sanitized

    if isinstance(value, list):
        return [sanitize_for_logging(item, max_string_length=max_string_length) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_for_logging(item, max_string_length=max_string_length) for item in value)

    if isinstance(value, bytes):
        return f"[{len(value)} bytes]"

    if isinstance(value, str):
        return _redact_string(value, max_length=max_string_length)

    return value


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    _STANDARD_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }

        for key, value in record.__dict__.items():
            if key in self._STANDARD_ATTRS:
                continue
            payload[key] = sanitize_for_logging(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level_name: str) -> None:
    global _LOGGING_CONFIGURED
    level = getattr(logging, level_name.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if _LOGGING_CONFIGURED:
        return

    if any(getattr(handler, "_nebula_handler", False) for handler in root.handlers):
        _LOGGING_CONFIGURED = True
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    setattr(handler, "_nebula_handler", True)
    root.addHandler(handler)
    _LOGGING_CONFIGURED = True
