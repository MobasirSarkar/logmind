from unittest.mock import AsyncMock

import httpx
import pytest

from simulator.engine import SimulationEngine
from simulator.models import ScenarioType, SimulationStatus
from simulator.shipper import AsyncLogShipper


@pytest.mark.asyncio
async def test_shipper_sends_batch_to_ingest_api():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 202
    mock_response.json.return_value = {
        "success": True,
        "data": {"status": "queued", "received_count": 2, "batch_id": "b-1"},
    }
    mock_client.post.return_value = mock_response

    shipper = AsyncLogShipper(base_url="http://test-ingest:8000", api_key="lmd_dev_key", client=mock_client)
    logs = [
        {"timestamp": "2026-09-05T12:00:00Z", "level": "INFO", "message": "hello", "service": "auth-service"}
    ]
    success, count = await shipper.ship_batch(tenant_id="acme", logs=logs)

    assert success is True
    assert count == 1
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://test-ingest:8000/api/v1/logs/ingest"
    assert call_args[1]["headers"]["X-Tenant-ID"] == "acme"
    assert call_args[1]["headers"]["X-API-Key"] == "lmd_dev_key"
    assert call_args[1]["json"] == {"logs": logs}


@pytest.mark.asyncio
async def test_simulation_engine_trigger_scenario():
    mock_shipper = AsyncMock(spec=AsyncLogShipper)
    mock_shipper.ship_batch.return_value = (True, 6)

    engine = SimulationEngine(shipper=mock_shipper)
    assert engine.get_status().status == SimulationStatus.IDLE

    record = await engine.trigger_scenario(
        tenant_id="acme",
        scenario_type=ScenarioType.PAYMENT_TIMEOUT,
    )

    assert record.scenario_type == ScenarioType.PAYMENT_TIMEOUT
    assert record.tenant_id == "acme"
    assert record.total_logs_emitted > 0
    mock_shipper.ship_batch.assert_called_once()

    # Ground-truth record persisted and retrievable
    retrieved = engine.get_run(record.run_id)
    assert retrieved is not None
    assert retrieved.run_id == record.run_id


@pytest.mark.asyncio
async def test_simulation_engine_start_stop_steady_state():
    mock_shipper = AsyncMock(spec=AsyncLogShipper)
    mock_shipper.ship_batch.return_value = (True, 6)

    engine = SimulationEngine(shipper=mock_shipper)
    await engine.start_steady_state(tenant_id="acme", rate_per_sec=10)

    status = engine.get_status()
    assert status.status == SimulationStatus.STEADY_STATE
    assert status.tenant_id == "acme"
    assert status.current_rate == 10

    await engine.stop()
    assert engine.get_status().status == SimulationStatus.IDLE
