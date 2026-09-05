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

def test_log_enricher_enrich_and_batch():
    from unittest.mock import MagicMock

    from app.services.normalizer import LogEnricher

    mock_embed = MagicMock()
    mock_embed.get_or_compute_embedding.return_value = [0.1] * 384
    enricher = LogEnricher(embedding_service=mock_embed)

    valid_item = {
        "timestamp": "2026-09-04T10:30:00Z",
        "level": "ERROR",
        "message": "Timeout on 192.168.1.1:8080",
        "error": {"error_type": "TimeoutError", "error_message": "Connection timed out"},
    }
    malformed_item = "not-a-dict"

    # 1. Single enrich
    rec = enricher.enrich(valid_item, tenant_id="t-1")
    assert rec.context.tenant_id == "t-1"
    assert rec.context.service == "default"
    assert rec.fingerprint is not None
    assert rec.fingerprint.content_hash is not None
    assert len(rec.fingerprint.embedding or []) == 384
    assert rec.error is not None
    assert rec.error.error_signature is not None

    # 2. Batch enrich
    valid_records, dlq_entries = enricher.enrich_batch([valid_item, malformed_item], tenant_id="t-1")
    assert len(valid_records) == 1
    assert len(dlq_entries) == 1
    assert dlq_entries[0].tenant_id == "t-1"
    assert "Log payload must be a JSON object" in dlq_entries[0].last_error
