from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_queue_service
from app.main import create_app
from simulator.api import get_simulation_engine
from simulator.engine import SimulationEngine
from simulator.models import ScenarioType
from simulator.shipper import AsyncLogShipper


@pytest.mark.asyncio
async def test_end_to_end_scenario_trigger_and_ingest():
    app = create_app()

    # In-memory mock queue to intercept ingested logs
    mock_queue = AsyncMock()
    mock_queue.is_queue_saturated.return_value = False
    mock_queue.enqueue_batch.return_value = 6
    app.dependency_overrides[get_queue_service] = lambda: mock_queue

    # Wire shipper transport directly to app ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        shipper = AsyncLogShipper(base_url="http://test", api_key="lmd_dev_key", client=test_client)
        engine = SimulationEngine(shipper=shipper)
        app.dependency_overrides[get_simulation_engine] = lambda: engine

        # 1. Trigger Scenario via API
        res = await test_client.post(
            "/api/v1/simulator/scenarios/trigger",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
            json={"scenario_type": ScenarioType.PAYMENT_TIMEOUT.value, "tenant_id": "acme"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        run_id = body["data"]["run_id"]
        assert body["data"]["root_cause_service"] == "payment-service"
        assert body["data"]["total_logs_emitted"] == 6

        # 2. Verify queue received the batch of 6 logs
        mock_queue.enqueue_batch.assert_called_once()
        tenant_arg, logs_arg = mock_queue.enqueue_batch.call_args[0]
        assert tenant_arg == "acme"
        assert len(logs_arg) == 6

        # 3. Retrieve ground-truth run record
        run_res = await test_client.get(
            f"/api/v1/simulator/runs/{run_id}",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "acme"},
        )
        assert run_res.status_code == 200
        run_data = run_res.json()["data"]
        assert run_data["run_id"] == run_id
        assert run_data["expected_diagnosis"] != ""
