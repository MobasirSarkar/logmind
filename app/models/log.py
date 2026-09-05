import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.constants import EmbeddingModel


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"

class HashType(str, Enum):
    SHA256 = "sha256"
    MD5 = "md5"

class ErrorStage(str, Enum):
    VALIDATION = "VALIDATION"
    SIGNATURE_EXTRACTION = "SIGNATURE_EXTRACTION"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"


class ServiceContext(BaseModel):
    tenant_id: str
    service: str
    environment: str = "production"

class TraceContext(BaseModel):
    trace_id: str
    span_id: str | None = None
    request_id: str | None = None

class HttpContext(BaseModel):
    method: str
    path: str
    status_code: int

class ErrorInfo(BaseModel):
    error_type: str
    error_message: str
    error_signature: str | None = None
    stack_trace: str | None = None

class LogFingerprint(BaseModel):
    content_hash: str
    signature_hash: str | None = None
    hash_type: HashType = HashType.SHA256
    embedding: list[float] | None = None
    model_name: str | None = EmbeddingModel.BGE_SMALL_EN.value

class LogRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    level: LogLevel
    message: str
    context: ServiceContext
    trace: TraceContext | None = None
    http: HttpContext | None = None
    error: ErrorInfo | None = None
    fingerprint: LogFingerprint | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

type RawLogPayload = dict[str, Any]

class DLQEntry(BaseModel):
    dlq_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retry_count: int
    error_stage: ErrorStage
    last_error: str
    raw_payload: RawLogPayload
