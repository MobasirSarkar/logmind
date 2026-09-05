import hashlib
import ipaddress
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.models.log import (
    DLQEntry,
    ErrorStage,
    HashType,
    LogFingerprint,
    LogRecord,
)


def is_valid_uuid(token: str) -> bool:
    try:
        _ = uuid.UUID(token.strip("(),:;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_ip(token: str) -> bool:
    clean = token.split(":")[0].strip("(),;[]")
    try:
        _ = ipaddress.ip_address(clean)
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_iso_timestamp(token: str) -> bool:
    try:
        _ = datetime.fromisoformat(token.strip("(),;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_hex(token: str) -> bool:
    clean = token.strip("(),;:").lower()
    if clean.startswith("0x") and len(clean) > 2:
        try:
            _ = int(clean, 16)
            return True
        except ValueError:
            return False
    return False

def is_valid_id(token: str) -> bool:
    clean = token.strip("(),;:[]")
    return clean.isdigit()

def sanitize_token(token: str) -> str:
    if is_valid_uuid(token):
        return "<UUID>"
    if is_valid_ip(token):
        if ":" in token:
            port = token.split(":")[-1]
            return f"<IP>:{port}"
        return "<IP>"
    if is_valid_iso_timestamp(token):
        return "<TIMESTAMP>"
    if is_valid_hex(token):
        return "<HEX>"
    if is_valid_id(token):
        return "<ID>"
    return token

def sanitize_error_message(message: str) -> str:
    tokens = message.split()
    sanitized_tokens: list[str] = [sanitize_token(tok) for tok in tokens]
    return " ".join(sanitized_tokens)

def generate_signature_hash(template: str) -> str:
    return hashlib.sha256(template.strip().encode("utf-8")).hexdigest()

def generate_content_hash(record: LogRecord) -> str:
    trace_id = record.trace.trace_id if record.trace else "no-trace"
    raw = f"{record.context.tenant_id}|{record.context.service}|{record.timestamp.isoformat()}|{record.message}|{trace_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LogEnricher:
    def __init__(self, embedding_service: Any | None = None):
        self.embeddings = embedding_service

    def enrich(self, raw: object, tenant_id: str) -> LogRecord:
        if not isinstance(raw, dict):
            raise TypeError(f"Log payload must be a JSON object, got {type(raw).__name__}")

        item = dict(raw)
        if "context" not in item:
            item["context"] = {
                "tenant_id": tenant_id,
                "service": item.get("service", "default"),
                "environment": item.get("environment", "production"),
            }
        elif isinstance(item["context"], dict) and not item["context"].get("tenant_id"):
            ctx = dict(item["context"])
            ctx["tenant_id"] = tenant_id
            item["context"] = ctx

        record = LogRecord.model_validate(item)
        c_hash = generate_content_hash(record)

        raw_text = record.error.error_message if record.error else record.message
        sanitized = sanitize_error_message(raw_text)
        s_hash = generate_signature_hash(sanitized)

        vector: list[float] | None = None
        if self.embeddings is not None:
            vector = self.embeddings.get_or_compute_embedding(s_hash, sanitized)

        if record.error:
            record.error.error_signature = sanitized

        record.fingerprint = LogFingerprint(
            content_hash=c_hash,
            signature_hash=s_hash,
            hash_type=HashType.SHA256,
            embedding=vector,
        )
        return record

    def enrich_batch(
        self, raw_items: Sequence[object], tenant_id: str
    ) -> tuple[list[LogRecord], list[DLQEntry]]:
        valid_records: list[LogRecord] = []
        dlq_entries: list[DLQEntry] = []

        for item in raw_items:
            try:
                record = self.enrich(item, tenant_id=tenant_id)
                valid_records.append(record)
            except Exception as exc:  # noqa: BLE001
                dlq = DLQEntry(
                    tenant_id=tenant_id,
                    retry_count=3,
                    error_stage=ErrorStage.VALIDATION,
                    last_error=str(exc),
                    raw_payload=item if isinstance(item, dict) else {"raw": str(item)},
                )
                dlq_entries.append(dlq)

        return valid_records, dlq_entries
