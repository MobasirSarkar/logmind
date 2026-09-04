# tests/unit/test_schemas.py
from datetime import datetime, timezone
from app.models.log import (
    LogLevel,
    HashType,
    ErrorStage,
    ServiceContext,
    TraceContext,
    HttpContext,
    ErrorInfo,
    LogFingerprint,
    LogRecord,
    DLQEntry,
)

def test_log_record_with_typed_metadata():
    record = LogRecord(
        timestamp=datetime.now(timezone.utc),
        level=LogLevel.ERROR,
        message="Payment timeout",
        context=ServiceContext(tenant_id="t-1", service="payment-service"),
        trace=TraceContext(trace_id="tr-100", span_id="sp-1"),
        http=HttpContext(method="POST", path="/v1/charge", status_code=504),
        error=ErrorInfo(error_type="GatewayTimeout", error_message="Stripe timeout after 8000ms"),
        fingerprint=LogFingerprint(content_hash="ch-abc123", hash_type=HashType.SHA256),
        metadata={"custom_key": 42}
    )
    assert record.level == LogLevel.ERROR
    assert record.context.service == "payment-service"
    assert record.http.status_code == 504
    assert record.metadata["custom_key"] == 42

def test_dlq_entry_with_error_stage_enum():
    entry = DLQEntry(
        tenant_id="t-1",
        retry_count=3,
        error_stage=ErrorStage.INDEXING,
        last_error="MapperParsingException",
        raw_payload={"raw": "data"}
    )
    assert entry.error_stage == ErrorStage.INDEXING
    assert entry.retry_count == 3
