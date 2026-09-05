import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"


class EventType(str, Enum):
    INITIAL_ERROR = "INITIAL_ERROR"
    CASCADING_ERROR = "CASCADING_ERROR"
    TIMEOUT = "TIMEOUT"
    GATEWAY_5XX = "GATEWAY_5XX"
    RECOVERY = "RECOVERY"


class DependencyType(str, Enum):
    HTTP = "HTTP"
    DATABASE = "DATABASE"
    CACHE = "CACHE"
    MESSAGE_QUEUE = "MESSAGE_QUEUE"
    GRPC = "GRPC"


class ServiceNode(BaseModel):
    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    name: str
    environment: str = "production"


class ServiceDependency(BaseModel):
    dependency_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    source_service: str
    target_service: str
    dependency_type: DependencyType = DependencyType.HTTP


class IncidentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    timestamp: datetime
    service: str
    event_type: EventType
    error_signature: str | None = None
    trace_id: str | None = None
    log_id: str | None = None
    message: str


class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.DETECTED
    started_at: datetime
    resolved_at: datetime | None = None
    trigger_service: str
    trigger_signature: str | None = None
    affected_services: list[str] = Field(default_factory=list)
    events: list[IncidentEvent] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
