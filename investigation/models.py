import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class InvestigationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DEGRADED_FALLBACK = "DEGRADED_FALLBACK"
    FAILED = "FAILED"


class EvidenceType(str, Enum):
    LOG = "LOG"
    TRACE = "TRACE"
    RUNBOOK = "RUNBOOK"
    HISTORICAL_INCIDENT = "HISTORICAL_INCIDENT"


class ToolName(str, Enum):
    SEARCH_LOGS = "search_logs"
    GET_TRACE = "get_trace"
    SEARCH_RUNBOOKS = "search_runbooks"
    GET_RELATED_INCIDENTS = "get_related_incidents"
    GET_SERVICE_DEPENDENCIES = "get_service_dependencies"


class EvidenceItem(BaseModel):
    evidence_type: EvidenceType
    reference_id: str
    service: str | None = None
    timestamp: datetime | None = None
    excerpt: str


class InvestigationStep(BaseModel):
    step_number: int
    tool_name: ToolName
    tool_input: dict[str, object]
    tool_output: dict[str, object]
    duration_ms: int


class InvestigationReport(BaseModel):
    investigation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    status: InvestigationStatus
    summary: str
    suspected_root_cause: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    affected_services: list[str]
    evidence: list[EvidenceItem] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    steps: list[InvestigationStep] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    is_fallback: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class IncidentNotFound(Exception):
    def __init__(self, incident_id: str) -> None:
        super().__init__(f"Incident not found: {incident_id}")
        self.incident_id = incident_id


# --- Tool Input & Output Models ---


class RunbookItem(BaseModel):
    id: str
    service: str
    title: str
    content: str
    score: float | None = None


class SearchLogsArgs(BaseModel):
    query: str = Field(description="Search query or error message")
    service: str | None = Field(
        default=None, description="Optional service name to filter by"
    )
    limit: int = Field(
        default=10, ge=1, le=50, description="Maximum number of logs (1-50)"
    )


class SearchLogsResult(BaseModel):
    count: int
    logs: list[dict[str, object]] = Field(default_factory=list)


class GetTraceArgs(BaseModel):
    trace_id: str = Field(description="Trace UUID")


class GetTraceResult(BaseModel):
    trace_id: str
    spans: list[dict[str, object]] = Field(default_factory=list)


class SearchRunbooksArgs(BaseModel):
    query: str = Field(description="Error or symptom to look up")
    service: str | None = Field(default=None, description="Optional service name")


class SearchRunbooksResult(BaseModel):
    runbooks: list[RunbookItem] = Field(default_factory=list)


class GetRelatedIncidentsArgs(BaseModel):
    signature_hash: str = Field(description="Error signature hash")


class GetRelatedIncidentsResult(BaseModel):
    incidents: list[dict[str, object]] = Field(default_factory=list)


class GetServiceDependenciesArgs(BaseModel):
    service: str = Field(description="Service name")


class GetServiceDependenciesResult(BaseModel):
    service: str
    upstream_callers: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)


# --- SQLAlchemy ORM Models ---


class InvestigationReportORM(Base):
    __tablename__ = "investigation_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suspected_root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    affected_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    evidence: Mapped[list["EvidenceItemORM"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    steps: Mapped[list["InvestigationStepORM"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="InvestigationStepORM.step_number",
        lazy="selectin",
    )


class EvidenceItemORM(Base):
    __tablename__ = "investigation_evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)

    report: Mapped[InvestigationReportORM] = relationship(back_populates="evidence")


class InvestigationStepORM(Base):
    __tablename__ = "investigation_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_input: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    tool_output: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    report: Mapped[InvestigationReportORM] = relationship(back_populates="steps")
