import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# --- Enums ---

class ServiceName(str, Enum):
    API_GATEWAY = "api-gateway"
    AUTH_SERVICE = "auth-service"
    ORDER_SERVICE = "order-service"
    PAYMENT_SERVICE = "payment-service"
    NOTIFICATION_SERVICE = "notification-service"


class ScenarioType(str, Enum):
    PAYMENT_TIMEOUT = "PAYMENT_TIMEOUT"
    DB_POOL_EXHAUSTION = "DB_POOL_EXHAUSTION"
    AUTH_DEPENDENCY_FAILURE = "AUTH_DEPENDENCY_FAILURE"
    RETRY_STORM = "RETRY_STORM"


class SimulationStatus(str, Enum):
    IDLE = "IDLE"
    STEADY_STATE = "STEADY_STATE"
    INJECTING_FAILURE = "INJECTING_FAILURE"
    DRAINING = "DRAINING"



# --- Control & Ground Truth Models ---

class ScenarioRunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario_type: ScenarioType
    tenant_id: str
    started_at: datetime
    ended_at: datetime | None = None
    root_cause_service: ServiceName
    root_cause_error: str
    affected_services: list[ServiceName]
    expected_diagnosis: str
    total_logs_emitted: int = 0
    scenario_metadata: dict[str, object] = Field(default_factory=dict)

class StartSimulationRequest(BaseModel):
    tenant_id: str = "tenant-default"
    rate_per_sec: int = Field(default=20, ge=1, le=500)


class TriggerScenarioRequest(BaseModel):
    scenario_type: ScenarioType
    tenant_id: str = "tenant-default"
    duration_seconds: int = Field(default=30, ge=5, le=300)
    intensity: float = Field(default=1.0, ge=0.1, le=5.0)


class SimulationStatusResponse(BaseModel):
    status: SimulationStatus
    tenant_id: str
    current_rate: int
    active_scenario: ScenarioType | None = None
    active_run_id: str | None = None


class StartSimulationResponse(BaseModel):
    status: str
    rate_per_sec: int
    tenant_id: str


class StopSimulationResponse(BaseModel):
    status: str
