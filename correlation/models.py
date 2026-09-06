import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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


# --- SQLAlchemy ORM Models ---


class ServiceORM(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), default="production")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ServiceDependencyORM(Base):
    __tablename__ = "service_dependencies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), nullable=False)
    dependency_type: Mapped[str] = mapped_column(
        String(32), default=DependencyType.HTTP.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class IncidentORM(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=IncidentStatus.DETECTED.value, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_service: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    affected_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    events: Mapped[list["IncidentEventORM"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEventORM.timestamp",
        lazy="selectin",
    )


class IncidentEventORM(Base):
    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    error_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    log_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    incident: Mapped[IncidentORM] = relationship(back_populates="events")
