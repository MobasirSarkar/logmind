import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from simulator.models import (
    ScenarioRunRecord,
    ScenarioType,
    SimulationStatus,
    SimulationStatusResponse,
)
from simulator.scenarios import SCENARIO_GENERATORS
from simulator.shipper import AsyncLogShipper
from simulator.trace import TraceGenerator

logger = logging.getLogger("uvicorn.error")


class SimulationEngine:
    def __init__(
        self,
        shipper: AsyncLogShipper | None = None,
        tracer: TraceGenerator | None = None,
    ):
        self.shipper: AsyncLogShipper = shipper or AsyncLogShipper()
        self.tracer: TraceGenerator = tracer or TraceGenerator()
        self.status: SimulationStatus = SimulationStatus.IDLE
        self.current_tenant: str = "tenant-default"
        self.current_rate: int = 0
        self.active_scenario: ScenarioType | None = None
        self.active_run_id: str | None = None
        self._runs: dict[str, ScenarioRunRecord] = {}
        self._background_task: asyncio.Task[None] | None = None

    def get_status(self) -> SimulationStatusResponse:
        return SimulationStatusResponse(
            status=self.status,
            tenant_id=self.current_tenant,
            current_rate=self.current_rate,
            active_scenario=self.active_scenario,
            active_run_id=self.active_run_id,
        )

    def get_run(self, run_id: str) -> ScenarioRunRecord | None:
        return self._runs.get(run_id)

    async def trigger_scenario(
        self,
        tenant_id: str,
        scenario_type: ScenarioType,
        duration_seconds: int = 30,
        intensity: float = 1.0,
    ) -> ScenarioRunRecord:
        generator_fn = SCENARIO_GENERATORS[scenario_type]
        logs, record = generator_fn(tenant_id, datetime.now(UTC))

        prev_status = self.status
        self.status = SimulationStatus.INJECTING_FAILURE
        record.scenario_metadata["duration_seconds"] = duration_seconds
        record.scenario_metadata["intensity"] = intensity
        self.active_run_id = record.run_id

        try:
            success, _ = await self.shipper.ship_batch(tenant_id=tenant_id, logs=logs)
            if not success:
                logger.warning("Failed to ship scenario logs for %s", scenario_type)
            self._runs[record.run_id] = record
            return record
        finally:
            self.status = prev_status
            self.active_scenario = None
            self.active_run_id = None

    async def start_steady_state(self, tenant_id: str, rate_per_sec: int = 20) -> None:
        await self.stop()
        self.current_tenant = tenant_id
        self.current_rate = rate_per_sec
        self.status = SimulationStatus.STEADY_STATE
        self._background_task = asyncio.create_task(self._steady_state_loop(tenant_id, rate_per_sec))
        logger.info(
            "Steady state simulation started for tenant '%s' at %d req/s",
            tenant_id,
            rate_per_sec,
        )

    async def stop(self) -> None:
        if self._background_task is not None:
            _ = self._background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._background_task
            self._background_task = None
        self.status = SimulationStatus.IDLE
        self.current_rate = 0
        self.active_scenario = None
        self.active_run_id = None
        logger.info("Simulation engine stopped")

    async def _steady_state_loop(self, tenant_id: str, rate_per_sec: int) -> None:
        delay = 1.0 / max(rate_per_sec, 1)
        try:
            while True:
                logs = self.tracer.generate_steady_state_trace(tenant_id)
                _ = await self.shipper.ship_batch(tenant_id, logs)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Exception in steady-state simulation loop: %s", exc)
