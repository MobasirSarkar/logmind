from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import ApiKeyDep, EmbeddingDep, EsDep, TenantIdHeader
from app.models.response import ApiResponse
from correlation.api import DbDep as CorrDbDep
from investigation.client import OpenAICompatibleClient
from investigation.db import InvestigationDatabaseManager
from investigation.engine import InvestigationEngine
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import InvestigationReport, InvestigationStep
from investigation.runbooks import RunbookService

_inv_db: InvestigationDatabaseManager | None = None
_runbook_service: RunbookService | None = None
_investigation_engine: InvestigationEngine | None = None


def get_investigation_db() -> InvestigationDatabaseManager:
    global _inv_db
    if _inv_db is None:
        _inv_db = InvestigationDatabaseManager()
    return _inv_db


def get_runbook_service(es: EsDep, embed: EmbeddingDep) -> RunbookService:
    global _runbook_service
    if _runbook_service is None:
        _runbook_service = RunbookService(es_service=es.es, embedding_service=embed)
    return _runbook_service

InvDbDep = Annotated[InvestigationDatabaseManager, Depends(get_investigation_db)]
RunbookDep = Annotated[RunbookService, Depends(get_runbook_service)]


def get_investigation_engine(
    inv_db: InvDbDep,
    es: EsDep,
    corr_db: CorrDbDep,
    runbooks: RunbookDep,
) -> InvestigationEngine:
    global _investigation_engine
    if _investigation_engine is None:
        llm = OpenAICompatibleClient()
        fallback = DeterministicFallbackEngine()
        _investigation_engine = InvestigationEngine(
            llm_client=llm,
            fallback_engine=fallback,
            db_manager=inv_db,
            es_service=es.es,
            corr_db_manager=corr_db,
            runbook_service=runbooks,
        )
    return _investigation_engine


async def close_investigation_services() -> None:
    global _inv_db, _runbook_service, _investigation_engine
    if _inv_db is not None:
        await _inv_db.close()
        _inv_db = None
    if _investigation_engine is not None and isinstance(
        _investigation_engine.llm, OpenAICompatibleClient
    ):
        await _investigation_engine.llm.close()
        _investigation_engine = None
    _runbook_service = None


InvestigationEngineDep = Annotated[InvestigationEngine, Depends(get_investigation_engine)]

router = APIRouter(tags=["AI Investigation"])


# --- Schemas ---

class IngestRunbookRequest(BaseModel):
    service: str
    title: str
    content: str


class IngestRunbookResponseData(BaseModel):
    runbook_id: str


class InvestigationStepsResponseData(BaseModel):
    investigation_id: str
    steps: list[InvestigationStep]


# --- Endpoints ---

@router.post("/api/v1/investigations/{incident_id}/start")
async def start_investigation(
    incident_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    corr_db: CorrDbDep,
    engine: InvestigationEngineDep,
) -> ApiResponse[InvestigationReport]:
    incident = await corr_db.get_incident(incident_id)
    if incident is None or incident.tenant_id != x_tenant_id:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    report = await engine.investigate_incident(incident)
    return ApiResponse[InvestigationReport].ok(report)


@router.get("/api/v1/investigations/{incident_id}")
async def get_investigation_report(
    incident_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    corr_db: CorrDbDep,
    inv_db: InvDbDep,
) -> ApiResponse[InvestigationReport]:
    incident = await corr_db.get_incident(incident_id)
    if incident is None or incident.tenant_id != x_tenant_id:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    report = await inv_db.get_report_by_incident(incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Investigation report not found")
    return ApiResponse[InvestigationReport].ok(report)


@router.get("/api/v1/investigations/{incident_id}/steps")
async def get_investigation_steps(
    incident_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    corr_db: CorrDbDep,
    inv_db: InvDbDep,
) -> ApiResponse[InvestigationStepsResponseData]:
    incident = await corr_db.get_incident(incident_id)
    if incident is None or incident.tenant_id != x_tenant_id:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    report = await inv_db.get_report_by_incident(incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Investigation report not found")

    return ApiResponse[InvestigationStepsResponseData].ok(
        InvestigationStepsResponseData(
            investigation_id=report.investigation_id, steps=report.steps
        )
    )


@router.post("/api/v1/investigations/{incident_id}/retry")
async def retry_investigation(
    incident_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    corr_db: CorrDbDep,
    engine: InvestigationEngineDep,
) -> ApiResponse[InvestigationReport]:
    return await start_investigation(
        incident_id=incident_id,
        x_tenant_id=x_tenant_id,
        _api_key=_api_key,
        corr_db=corr_db,
        engine=engine,
    )


@router.post("/api/v1/runbooks")
async def ingest_runbook(
    req: IngestRunbookRequest,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    runbooks: RunbookDep,
) -> ApiResponse[IngestRunbookResponseData]:
    rid = await runbooks.ingest_runbook(
        tenant_id=x_tenant_id,
        service=req.service,
        title=req.title,
        markdown_content=req.content,
    )
    return ApiResponse[IngestRunbookResponseData].ok(
        IngestRunbookResponseData(runbook_id=rid)
    )
