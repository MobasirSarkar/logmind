from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import ApiKeyDep, EsDep, TenantIdHeader
from app.models.response import ApiResponse
from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine
from correlation.models import (
    DependencyType,
    Incident,
    IncidentStatus,
    ServiceDependency,
)

_db_manager: DatabaseManager | None = None
_correlation_engine: CorrelationEngine | None = None


def get_database_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_correlation_engine(
    es: EsDep,
    db: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> CorrelationEngine:
    global _correlation_engine
    if _correlation_engine is None:
        _correlation_engine = CorrelationEngine(es_service=es.es, db_manager=db)
    return _correlation_engine


async def close_database_manager() -> None:
    global _db_manager, _correlation_engine
    if _db_manager is not None:
        await _db_manager.close()
        _db_manager = None
    _correlation_engine = None


DbDep = Annotated[DatabaseManager, Depends(get_database_manager)]
CorrelationDep = Annotated[CorrelationEngine, Depends(get_correlation_engine)]
StatusQuery = Annotated[IncidentStatus | None, Query()]
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


# --- Topology Endpoints ---

@router.get("/api/v1/topology")
async def get_topology(
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    db: DbDep,
) -> ApiResponse[TopologyResponseData]:
    deps = await db.get_dependencies(x_tenant_id)
    return ApiResponse[TopologyResponseData].ok(
        TopologyResponseData(dependencies=deps)
    )


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
        tenant_id=x_tenant_id, lookback_seconds=req.lookback_seconds
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
