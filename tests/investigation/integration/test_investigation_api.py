from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_es_service
from app.main import create_app
from correlation.api import get_database_manager as get_corr_db
from correlation.models import Incident, IncidentSeverity, IncidentStatus
from investigation.api import get_investigation_db


@pytest.mark.asyncio
async def test_investigation_api_endpoints():
    app = create_app()
    mock_es = AsyncMock()
    mock_es.search.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
    mock_es.index.return_value = {"result": "created"}
    app.dependency_overrides[get_es_service] = lambda: mock_es
    # Ensure tables
    corr_db = get_corr_db()
    await corr_db.ensure_tables()
    inv_db = get_investigation_db()
    await inv_db.ensure_tables()

    # Seed incident in DB
    now = datetime.now(UTC)
    incident = Incident(
        incident_id="inc-api-1",
        tenant_id="acme",
        title="Stripe Timeout",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="payment-service",
    )
    await corr_db.save_incident(incident)

    headers = {"X-Tenant-ID": "acme", "X-API-Key": "lmd_dev_key"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Start investigation
        start_res = await ac.post("/api/v1/investigations/inc-api-1/start", headers=headers)
        assert start_res.status_code == 200
        start_body = start_res.json()
        assert start_body["success"] is True
        assert start_body["data"]["incident_id"] == "inc-api-1"

        # 2. Get investigation report
        get_res = await ac.get("/api/v1/investigations/inc-api-1", headers=headers)
        assert get_res.status_code == 200
        get_body = get_res.json()
        assert get_body["success"] is True
        assert get_body["data"]["incident_id"] == "inc-api-1"

        # 3. Get investigation steps
        steps_res = await ac.get("/api/v1/investigations/inc-api-1/steps", headers=headers)
        assert steps_res.status_code == 200
        steps_body = steps_res.json()
        assert steps_body["success"] is True
        assert "steps" in steps_body["data"]

        # 4. Ingest runbook
        rb_res = await ac.post(
            "/api/v1/runbooks",
            headers=headers,
            json={
                "service": "payment-service",
                "title": "Payment Runbook",
                "content": "Failover guide",
            },
        )
        assert rb_res.status_code == 200
        rb_body = rb_res.json()
        assert rb_body["success"] is True
        assert "runbook_id" in rb_body["data"]
