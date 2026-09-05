from datetime import UTC, datetime

from correlation.models import (
    EventType,
    Incident,
    IncidentEvent,
    IncidentSeverity,
    IncidentStatus,
)
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import EvidenceType, InvestigationStatus


def test_fallback_engine_generates_valid_report():
    now = datetime.now(UTC)
    incident = Incident(
        incident_id="inc-500",
        tenant_id="acme",
        title="Payment Service Latency Spike",
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.DETECTED,
        started_at=now,
        trigger_service="payment-service",
        trigger_signature="GatewayTimeoutException",
        affected_services=["payment-service", "order-service"],
        events=[
            IncidentEvent(
                incident_id="inc-500",
                timestamp=now,
                service="payment-service",
                event_type=EventType.INITIAL_ERROR,
                message="Stripe gateway timeout after 8000ms",
                log_id="log-pay-1",
                trace_id="tr-abc",
            )
        ],
    )

    fallback_engine = DeterministicFallbackEngine()
    report = fallback_engine.generate_report(incident, error_reason="Timeout after 15s")

    assert report.is_fallback is True
    assert report.status == InvestigationStatus.DEGRADED_FALLBACK
    assert report.confidence_score == 0.50
    assert report.incident_id == "inc-500"
    assert "payment-service" in report.suspected_root_cause
    assert len(report.evidence) >= 1
    assert report.evidence[0].evidence_type in (EvidenceType.LOG, EvidenceType.TRACE)
    assert report.metadata["fallback_reason"] == "Timeout after 15s"
