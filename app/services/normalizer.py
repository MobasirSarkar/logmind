import hashlib
import ipaddress
import uuid
from datetime import datetime
from typing import List
from app.models.log import LogRecord

def is_valid_uuid(token: str) -> bool:
    try:
        uuid.UUID(token.strip("(),:;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_ip(token: str) -> bool:
    clean = token.split(":")[0].strip("(),;[]")
    try:
        ipaddress.ip_address(clean)
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_iso_timestamp(token: str) -> bool:
    try:
        datetime.fromisoformat(token.strip("(),;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_hex(token: str) -> bool:
    clean = token.strip("(),;:").lower()
    if clean.startswith("0x") and len(clean) > 2:
        try:
            int(clean, 16)
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
    sanitized_tokens: List[str] = [sanitize_token(tok) for tok in tokens]
    return " ".join(sanitized_tokens)

def generate_signature_hash(template: str) -> str:
    return hashlib.sha256(template.strip().encode("utf-8")).hexdigest()

def generate_content_hash(record: LogRecord) -> str:
    trace_id = record.trace.trace_id if record.trace else "no-trace"
    raw = f"{record.context.tenant_id}|{record.context.service}|{record.timestamp.isoformat()}|{record.message}|{trace_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
