from datetime import UTC, datetime

from correlation.graph import DependencyGraph
from correlation.models import (
    DependencyType,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    ServiceDependency,
)


def test_dependency_merger_detects_downstream_root_cause():
    graph = DependencyGraph()
    graph.add_dependency(
        ServiceDependency(
            tenant_id="t-1",
            source_service="api-gateway",
            target_service="order-service",
            dependency_type=DependencyType.HTTP,
        )
    )
    graph.add_dependency(
        ServiceDependency(
            tenant_id="t-1",
            source_service="order-service",
            target_service="payment-service",
            dependency_type=DependencyType.HTTP,
        )
    )

    now = datetime.now(UTC)
    active_payment_incident = Incident(
        incident_id="inc-payment-1",
        tenant_id="t-1",
        title="Payment Outage",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="payment-service",
        affected_services=["payment-service"],
    )

    # When order-service fails, it should merge into the active payment-service incident
    merged = graph.find_active_downstream_incident(
        tenant_id="t-1",
        service="order-service",
        active_incidents=[active_payment_incident],
    )
    assert merged is not None
    assert merged.incident_id == "inc-payment-1"


def test_dependency_merger_returns_none_when_no_active_downstream():
    graph = DependencyGraph()
    graph.add_dependency(
        ServiceDependency(
            tenant_id="t-1",
            source_service="order-service",
            target_service="payment-service",
            dependency_type=DependencyType.HTTP,
        )
    )

    now = datetime.now(UTC)
    active_auth_incident = Incident(
        incident_id="inc-auth-1",
        tenant_id="t-1",
        title="Auth Outage",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="auth-service",
        affected_services=["auth-service"],
    )

    # order-service does not depend on auth-service, so should return None
    merged = graph.find_active_downstream_incident(
        tenant_id="t-1",
        service="order-service",
        active_incidents=[active_auth_incident],
    )
    assert merged is None
