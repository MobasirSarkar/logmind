from datetime import UTC, datetime

from investigation.models import (
    EvidenceItem,
    EvidenceType,
    InvestigationReport,
    InvestigationStatus,
    InvestigationStep,
    ToolName,
)


def test_investigation_report_model():
    now = datetime.now(UTC)
    evidence = EvidenceItem(
        evidence_type=EvidenceType.LOG,
        reference_id="log-12345",
        service="payment-service",
        timestamp=now,
        excerpt="GatewayTimeoutException: Stripe timed out after 8000ms",
    )
    step = InvestigationStep(
        step_number=1,
        tool_name=ToolName.SEARCH_LOGS,
        tool_input={"query": "GatewayTimeoutException"},
        tool_output={"count": 1},
        duration_ms=120,
    )
    report = InvestigationReport(
        incident_id="inc-100",
        status=InvestigationStatus.COMPLETED,
        summary="Payment gateway timeout cascade",
        suspected_root_cause="Stripe upstream timeout in payment-service",
        confidence_score=0.95,
        affected_services=["payment-service", "order-service"],
        evidence=[evidence],
        recommended_actions=["Check Stripe status", "Increase circuit breaker sensitivity"],
        steps=[step],
        started_at=now,
        completed_at=now,
        is_fallback=False,
    )
    assert report.status == InvestigationStatus.COMPLETED
    assert report.confidence_score == 0.95
    assert len(report.evidence) == 1
    assert report.evidence[0].evidence_type == EvidenceType.LOG
    assert not report.is_fallback
