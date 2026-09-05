from datetime import UTC, datetime

from correlation.models import (
    DependencyType,
    EventType,
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentStatus,
    ServiceDependency,
    ServiceNode,
)


def test_incident_and_event_models():
    now = datetime.now(UTC)
    node = ServiceNode(tenant_id="t-1", name="payment-service")
    assert node.name == "payment-service"

    dep = ServiceDependency(
        tenant_id="t-1",
        source_service="order-service",
        target_service="payment-service",
        dependency_type=DependencyType.HTTP,
    )
    assert dep.source_service == "order-service"

    event = IncidentEvent(
        incident_id="inc-1",
        timestamp=now,
        service="payment-service",
        event_type=EventType.INITIAL_ERROR,
        message="GatewayTimeoutException: Stripe timed out",
    )
    assert event.event_type == EventType.INITIAL_ERROR

    incident = Incident(
        tenant_id="t-1",
        title="Payment Gateway Timeout",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="payment-service",
        affected_services=["payment-service", "order-service"],
        events=[event],
        metadata={"cascade_depth": 2},
    )
    assert incident.severity == IncidentSeverity.HIGH
    assert incident.status == IncidentStatus.DETECTED
    assert len(incident.events) == 1
    assert incident.metadata["cascade_depth"] == 2
