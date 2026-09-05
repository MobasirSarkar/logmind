import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
