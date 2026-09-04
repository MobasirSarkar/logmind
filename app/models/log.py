import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

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

TMetadata = TypeVar("TMetadata")
TPayload = TypeVar("TPayload")

class ServiceContext(BaseModel):
    tenant_id: str
    service: str
    environment: str = "production"

class TraceContext(BaseModel):
    trace_id: str
    span_id: Optional[str] = None
    request_id: Optional[str] = None

class HttpContext(BaseModel):
    method: str
    path: str
    status_code: int

class ErrorInfo(BaseModel):
    error_type: str
    error_message: str
    error_signature: Optional[str] = None
    stack_trace: Optional[str] = None

class LogFingerprint(BaseModel):
    content_hash: str
    signature_hash: Optional[str] = None
    hash_type: HashType = HashType.SHA256
    embedding: Optional[list[float]] = None
    model_name: Optional[str] = "BAAI/bge-small-en-v1.5"

class LogRecord(BaseModel, Generic[TMetadata]):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    level: LogLevel
    message: str
    context: ServiceContext
    trace: Optional[TraceContext] = None
    http: Optional[HttpContext] = None
    error: Optional[ErrorInfo] = None
    fingerprint: Optional[LogFingerprint] = None
    metadata: TMetadata = Field(default_factory=dict)

class DLQEntry(BaseModel, Generic[TPayload]):
    dlq_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    failed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int
    error_stage: ErrorStage
    last_error: str
    raw_payload: TPayload
