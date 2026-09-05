from datetime import UTC, datetime

import pytest

from investigation.db import InvestigationDatabaseManager
from investigation.models import (
    EvidenceItem,
    EvidenceType,
    InvestigationReport,
    InvestigationStatus,
    InvestigationStep,
    ToolName,
)


@pytest.mark.asyncio
async def test_investigation_db_crud():
    db = InvestigationDatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    now = datetime.now(UTC)
    report = InvestigationReport(
        incident_id="inc-1",
        status=InvestigationStatus.COMPLETED,
        summary="Payment timeout cascade",
        suspected_root_cause="Stripe upstream latency",
        confidence_score=0.90,
        affected_services=["payment-service", "order-service"],
        evidence=[
            EvidenceItem(
                evidence_type=EvidenceType.LOG,
                reference_id="log-1",
                service="payment-service",
                timestamp=now,
                excerpt="GatewayTimeout",
            )
        ],
        steps=[
            InvestigationStep(
                step_number=1,
                tool_name=ToolName.GET_TRACE,
                tool_input={"trace_id": "tr-100"},
                tool_output={"count": 3},
                duration_ms=50,
            )
        ],
        recommended_actions=["Failover gateway"],
        started_at=now,
        completed_at=now,
        is_fallback=False,
    )
    await db.save_report(report)

    fetched = await db.get_report_by_incident("inc-1")
    assert fetched is not None
    assert fetched.summary == "Payment timeout cascade"
    assert len(fetched.evidence) == 1
    assert fetched.evidence[0].evidence_type == EvidenceType.LOG
    assert len(fetched.steps) == 1
    assert fetched.steps[0].tool_name == ToolName.GET_TRACE

    await db.close()
