from datetime import UTC, datetime

import pytest

from correlation.db import DatabaseManager
from correlation.models import (
    DependencyType,
    EventType,
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentStatus,
    ServiceDependency,
)


@pytest.mark.asyncio
async def test_database_manager_crud():
    db = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    # 1. Dependency mapping
    await db.save_dependency(
        ServiceDependency(
            tenant_id="t-1",
            source_service="order-service",
            target_service="payment-service",
            dependency_type=DependencyType.HTTP,
        )
    )
    deps = await db.get_dependencies("t-1")
    assert len(deps) == 1
    assert deps[0].source_service == "order-service"

    # 2. Incident insertion
    now = datetime.now(UTC)
    incident = Incident(
        incident_id="inc-100",
        tenant_id="t-1",
        title="Payment Provider Timeout",
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="payment-service",
        affected_services=["payment-service"],
        events=[
            IncidentEvent(
                incident_id="inc-100",
                timestamp=now,
                service="payment-service",
                event_type=EventType.INITIAL_ERROR,
                message="Stripe timeout",
            )
        ],
    )
    await db.save_incident(incident)

    fetched = await db.get_incident("inc-100")
    assert fetched is not None
    assert fetched.title == "Payment Provider Timeout"
    assert len(fetched.events) == 1
    assert fetched.events[0].service == "payment-service"

    # 3. List incidents
    incidents = await db.list_incidents("t-1")
    assert len(incidents) == 1
    assert incidents[0].incident_id == "inc-100"

    # 4. Update status
    updated = await db.update_incident_status("inc-100", IncidentStatus.RESOLVED)
    assert updated is not None
    assert updated.status == IncidentStatus.RESOLVED

    await db.close()
