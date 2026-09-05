from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import ApiKeyDep
from app.models.response import ApiResponse
from simulator.engine import SimulationEngine
from simulator.models import (
    ScenarioRunRecord,
    SimulationStatusResponse,
    StartSimulationRequest,
    StartSimulationResponse,
    StopSimulationResponse,
    TriggerScenarioRequest,
)

_simulation_engine: SimulationEngine | None = None


def get_simulation_engine() -> SimulationEngine:
    global _simulation_engine
    if _simulation_engine is None:
        _simulation_engine = SimulationEngine()
    return _simulation_engine


async def close_simulation_engine() -> None:
    global _simulation_engine
    if _simulation_engine is not None:
        await _simulation_engine.stop()
        await _simulation_engine.shipper.close()
        _simulation_engine = None

EngineDep = Annotated[SimulationEngine, Depends(get_simulation_engine)]

router = APIRouter(prefix="/api/v1/simulator", tags=["Simulator"])


@router.get("/status")
async def get_status(
    _api_key: ApiKeyDep, engine: EngineDep
) -> ApiResponse[SimulationStatusResponse]:
    status = engine.get_status()
    return ApiResponse[SimulationStatusResponse].ok(status)


@router.post("/start")
async def start_simulation(
    req: StartSimulationRequest,
    _api_key: ApiKeyDep,
    engine: EngineDep,
) -> ApiResponse[StartSimulationResponse]:
    await engine.start_steady_state(
        tenant_id=req.tenant_id, rate_per_sec=req.rate_per_sec
    )
    data = StartSimulationResponse(
        status="started",
        rate_per_sec=req.rate_per_sec,
        tenant_id=req.tenant_id,
    )
    return ApiResponse[StartSimulationResponse].ok(data)


@router.post("/stop")
async def stop_simulation(
    _api_key: ApiKeyDep, engine: EngineDep
) -> ApiResponse[StopSimulationResponse]:
    await engine.stop()
    return ApiResponse[StopSimulationResponse].ok(
        StopSimulationResponse(status="stopped")
    )


@router.post("/scenarios/trigger")
async def trigger_scenario(
    req: TriggerScenarioRequest,
    _api_key: ApiKeyDep,
    engine: EngineDep,
) -> ApiResponse[ScenarioRunRecord]:
    record = await engine.trigger_scenario(
        tenant_id=req.tenant_id,
        scenario_type=req.scenario_type,
        duration_seconds=req.duration_seconds,
        intensity=req.intensity,
    )
    return ApiResponse[ScenarioRunRecord].ok(record)


@router.get("/runs/{run_id}")
async def get_scenario_run(
    run_id: str,
    _api_key: ApiKeyDep,
    engine: EngineDep,
) -> ApiResponse[ScenarioRunRecord]:
    record = engine.get_run(run_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Scenario run '{run_id}' not found"
        )
    return ApiResponse[ScenarioRunRecord].ok(record)
