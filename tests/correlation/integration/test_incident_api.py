import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from correlation.api import get_database_manager


@pytest.mark.asyncio
async def test_incident_api_list_and_topology():
    app = create_app()
    db = get_database_manager()
    await db.ensure_tables()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"}

        # 1. Register dependency
        dep_res = await ac.post(
            "/api/v1/topology/dependencies",
            headers=headers,
            json={
                "source_service": "order-service",
                "target_service": "payment-service",
                "dependency_type": "HTTP",
            },
        )
        assert dep_res.status_code == 200
        dep_body = dep_res.json()
        assert dep_body["success"] is True

        # 2. Get topology
        topo_res = await ac.get("/api/v1/topology", headers=headers)
        assert topo_res.status_code == 200
        topo_body = topo_res.json()
        assert topo_body["success"] is True
        assert len(topo_body["data"]["dependencies"]) >= 1

        # 3. List incidents
        inc_res = await ac.get("/api/v1/incidents", headers=headers)
        assert inc_res.status_code == 200
        inc_body = inc_res.json()
        assert inc_body["success"] is True
        assert "items" in inc_body["data"]

        # 4. Insert incident directly in DB and test get & patch endpoints
        from datetime import UTC, datetime

        from correlation.models import Incident, IncidentSeverity, IncidentStatus
        test_inc = Incident(
            incident_id="inc-api-test",
            tenant_id="t-1",
            title="Test Incident",
            severity=IncidentSeverity.HIGH,
            status=IncidentStatus.DETECTED,
            started_at=datetime.now(UTC),
            trigger_service="payment-service",
        )
        await db.save_incident(test_inc)

        # 5. Get single incident
        get_res = await ac.get("/api/v1/incidents/inc-api-test", headers=headers)
        assert get_res.status_code == 200
        get_body = get_res.json()
        assert get_body["success"] is True
        assert get_body["data"]["incident_id"] == "inc-api-test"

        # 6. Update status
        patch_res = await ac.patch(
            "/api/v1/incidents/inc-api-test/status",
            headers=headers,
            json={"status": "INVESTIGATING"},
        )
        assert patch_res.status_code == 200
        patch_body = patch_res.json()
        assert patch_body["success"] is True
        assert patch_body["data"]["status"] == "INVESTIGATING"

        # 7. Evaluate endpoint
        eval_res = await ac.post(
            "/api/v1/incidents/evaluate",
            headers=headers,
            json={"lookback_seconds": 60},
        )
        assert eval_res.status_code == 200
        eval_body = eval_res.json()
        assert eval_body["success"] is True
