from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import ApiKeyDep, TenantIdHeader
from app.models.response import ApiResponse
from correlation.deps import (
    CorrelationDep,
    DbDep,
    StatusQuery,
    close_database_manager,
    get_correlation_engine,
    get_database_manager,
)
from correlation.models import (
    DependencyType,
    Incident,
    IncidentStatus,
    ServiceDependency,
)

__all__ = [
    "CorrelationDep",
    "DbDep",
    "StatusQuery",
    "close_database_manager",
    "get_correlation_engine",
    "get_database_manager",
    "router",
]
router = APIRouter(tags=["Correlation & Incidents"])


# --- Request & Response Models ---


class RegisterDependencyRequest(BaseModel):
    source_service: str
    target_service: str
    dependency_type: DependencyType = DependencyType.HTTP


class TopologyResponseData(BaseModel):
    dependencies: list[ServiceDependency]


class IncidentListResponseData(BaseModel):
    items: list[Incident]
    count: int


class UpdateStatusRequest(BaseModel):
    status: IncidentStatus


class EvaluateRequest(BaseModel):
    lookback_seconds: int = Field(default=60, ge=10, le=3600)
    min_error_count: int | None = Field(default=1, ge=1, le=1000)


# --- Topology Endpoints ---


@router.get("/api/v1/topology")
async def get_topology(
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
) -> ApiResponse[TopologyResponseData]:
    deps = await db.get_dependencies(x_tenant_id)
    return ApiResponse[TopologyResponseData].ok(TopologyResponseData(dependencies=deps))


@router.post("/api/v1/topology/dependencies")
async def register_dependency(
    req: RegisterDependencyRequest,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
) -> ApiResponse[ServiceDependency]:
    dep = ServiceDependency(
        tenant_id=x_tenant_id,
        source_service=req.source_service,
        target_service=req.target_service,
        dependency_type=req.dependency_type,
    )
    saved = await db.save_dependency(dep)
    return ApiResponse[ServiceDependency].ok(saved)


# --- Incident Endpoints ---


@router.get("/api/v1/incidents")
async def list_incidents(
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
    status: StatusQuery = None,
) -> ApiResponse[IncidentListResponseData]:
    incidents = await db.list_incidents(tenant_id=x_tenant_id, status=status)
    return ApiResponse[IncidentListResponseData].ok(
        IncidentListResponseData(items=incidents, count=len(incidents))
    )


@router.get("/api/v1/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
) -> ApiResponse[Incident]:
    incident = await db.get_incident(incident_id)
    if incident is None or incident.tenant_id != x_tenant_id:
        raise HTTPException(status_code=404, detail="Incident not found")
    return ApiResponse[Incident].ok(incident)


@router.post("/api/v1/incidents/evaluate")
async def evaluate_incidents(
    req: EvaluateRequest,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    engine: CorrelationDep,
) -> ApiResponse[IncidentListResponseData]:
    incidents = await engine.evaluate_tenant(
        tenant_id=x_tenant_id,
        lookback_seconds=req.lookback_seconds,
        min_error_count=req.min_error_count,
    )
    return ApiResponse[IncidentListResponseData].ok(
        IncidentListResponseData(items=incidents, count=len(incidents))
    )


@router.patch("/api/v1/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    req: UpdateStatusRequest,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
) -> ApiResponse[Incident]:
    incident = await db.get_incident(incident_id)
    if incident is None or incident.tenant_id != x_tenant_id:
        raise HTTPException(status_code=404, detail="Incident not found")

    updated = await db.update_incident_status(incident_id, req.status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return ApiResponse[Incident].ok(updated)
