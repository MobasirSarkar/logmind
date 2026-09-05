from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine
from correlation.models import DependencyType, EventType, ServiceDependency
from simulator.scenarios import generate_payment_timeout_scenario


@pytest.mark.asyncio
async def test_end_to_end_payment_timeout_correlation():
    db = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    # 1. Register topology: api-gateway -> order-service -> payment-service
    await db.save_dependency(
        ServiceDependency(
            tenant_id="acme",
            source_service="api-gateway",
            target_service="order-service",
            dependency_type=DependencyType.HTTP,
        )
    )
    await db.save_dependency(
        ServiceDependency(
            tenant_id="acme",
            source_service="order-service",
            target_service="payment-service",
            dependency_type=DependencyType.HTTP,
        )
    )

    # 2. Generate synthetic incident logs via simulator
    now = datetime.now(UTC)
    logs, ground_truth = generate_payment_timeout_scenario(tenant_id="acme", base_time=now)

    # 3. Wire mock ES service returning synthetic logs
    mock_es = AsyncMock()
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": len(logs)},
            "hits": [{"_source": log} for log in logs],
        }
    }

    engine = CorrelationEngine(es_service=mock_es, db_manager=db)
    incidents = await engine.correlate_logs(tenant_id="acme", logs=logs)

    # 4. Verify exactly ONE incident was created, rooted in payment-service
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.trigger_service == ground_truth.root_cause_service.value
    assert "payment-service" in inc.affected_services
    assert "order-service" in inc.affected_services
    assert "api-gateway" in inc.affected_services

    # 5. Verify event categorization
    initial_events = [e for e in inc.events if e.event_type == EventType.INITIAL_ERROR]
    assert len(initial_events) == 1
    assert initial_events[0].service == "payment-service"

    cascading_events = [e for e in inc.events if e.event_type == EventType.CASCADING_ERROR]
    assert len(cascading_events) >= 2

    # 6. Verify persistence in DB
    persisted = await db.get_incident(inc.incident_id)
    assert persisted is not None
    assert persisted.trigger_service == "payment-service"
    assert len(persisted.events) == len(inc.events)

    await db.close()
