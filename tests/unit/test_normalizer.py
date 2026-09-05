# tests/unit/test_normalizer.py
from datetime import UTC, datetime

from app.models.log import LogLevel, LogRecord, ServiceContext, TraceContext
from app.services.normalizer import (
    generate_content_hash,
    generate_signature_hash,
    sanitize_error_message,
)


def test_sanitize_tokens_without_regex():
    raw_message = "Connection to 192.168.1.50:5432 failed for user 91024 with uuid 123e4567-e89b-12d3-a456-426614174000 at 0x7ffd98"
    sanitized = sanitize_error_message(raw_message)
    assert "<IP>" in sanitized
    assert "<ID>" in sanitized
    assert "<UUID>" in sanitized
    assert "<HEX>" in sanitized
    assert "192.168.1.50" not in sanitized
    assert "91024" not in sanitized
    assert "123e4567-e89b-12d3-a456-426614174000" not in sanitized

def test_signature_hash_deterministic():
    template = "Connection to <IP>:5432 failed for user <ID>"
    hash1 = generate_signature_hash(template)
    hash2 = generate_signature_hash(template)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest

def test_content_hash_idempotency():
    ts = datetime(2026, 9, 4, 10, 30, 0, tzinfo=UTC)
    rec1 = LogRecord(
        timestamp=ts,
        level=LogLevel.ERROR,
        message="Failure",
        context=ServiceContext(tenant_id="t-1", service="payment"),
        trace=TraceContext(trace_id="tr-1")
    )
    rec2 = LogRecord(
        timestamp=ts,
        level=LogLevel.ERROR,
        message="Failure",
        context=ServiceContext(tenant_id="t-1", service="payment"),
        trace=TraceContext(trace_id="tr-1")
    )
    assert generate_content_hash(rec1) == generate_content_hash(rec2)
