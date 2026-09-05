from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from simulator.api import get_simulation_engine
from simulator.engine import SimulationEngine
from simulator.models import (
    ScenarioRunRecord,
    ScenarioType,
    ServiceName,
    SimulationStatus,
    SimulationStatusResponse,
)


@pytest.mark.asyncio
async def test_simulator_api_status_endpoint():
    app = create_app()
    mock_engine = AsyncMock(spec=SimulationEngine)
    mock_engine.get_status.return_value = SimulationStatusResponse(
        status=SimulationStatus.IDLE,
        tenant_id="acme",
        current_rate=0,
    )
    app.dependency_overrides[get_simulation_engine] = lambda: mock_engine

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/simulator/status",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "IDLE"


@pytest.mark.asyncio
async def test_simulator_api_start_and_stop_endpoints():
    app = create_app()
    mock_engine = AsyncMock(spec=SimulationEngine)
    app.dependency_overrides[get_simulation_engine] = lambda: mock_engine

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Start
        res = await ac.post(
            "/api/v1/simulator/start",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
            json={"tenant_id": "acme", "rate_per_sec": 30},
        )
        assert res.status_code == 200
        mock_engine.start_steady_state.assert_called_once_with(tenant_id="acme", rate_per_sec=30)

        # Stop
        res = await ac.post(
            "/api/v1/simulator/stop",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
        )
        assert res.status_code == 200
        mock_engine.stop.assert_called_once()


@pytest.mark.asyncio
async def test_simulator_api_trigger_scenario_and_get_run():
    app = create_app()
    mock_engine = AsyncMock(spec=SimulationEngine)
    fake_record = ScenarioRunRecord(
        run_id="run-12345",
        scenario_type=ScenarioType.PAYMENT_TIMEOUT,
        tenant_id="acme",
        started_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC),
        root_cause_service=ServiceName.PAYMENT_SERVICE,
        root_cause_error="Stripe timeout",
        affected_services=[ServiceName.PAYMENT_SERVICE],
        expected_diagnosis="Payment timeout",
        total_logs_emitted=6,
    )
    mock_engine.trigger_scenario.return_value = fake_record
    mock_engine.get_run.return_value = fake_record
    app.dependency_overrides[get_simulation_engine] = lambda: mock_engine

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Trigger
        res = await ac.post(
            "/api/v1/simulator/scenarios/trigger",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
            json={
                "scenario_type": "PAYMENT_TIMEOUT",
                "tenant_id": "acme",
                "duration_seconds": 30,
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"]["run_id"] == "run-12345"

        # Get run
        res = await ac.get(
            "/api/v1/simulator/runs/run-12345",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["run_id"] == "run-12345"
