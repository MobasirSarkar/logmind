from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine
from investigation.client import ChatCompletionResponse
from investigation.db import InvestigationDatabaseManager
from investigation.engine import InvestigationEngine
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import EvidenceType, InvestigationStatus
from simulator.scenarios import generate_payment_timeout_scenario


@pytest.mark.asyncio
async def test_full_pipeline_incident_to_ai_diagnosis():
    # 1. Generate synthetic failure cascade via Service 2 simulator
    now = datetime.now(UTC)
    logs, ground_truth = generate_payment_timeout_scenario(tenant_id="acme", base_time=now)

    # 2. Correlate logs into an incident via Service 3
    corr_db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await corr_db.ensure_tables()
    mock_es = AsyncMock()
    corr_engine = CorrelationEngine(es_service=mock_es, db_manager=corr_db)
    incidents = await corr_engine.correlate_logs("acme", logs)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.trigger_service == ground_truth.root_cause_service.value

    # 3. Investigate with AI engine (Service 4)
    inv_db = InvestigationDatabaseManager("sqlite+aiosqlite:///:memory:")
    await inv_db.ensure_tables()

    mock_llm = AsyncMock()
    mock_llm.chat_completion.return_value = ChatCompletionResponse(
        content="""```json
{
  "summary": "Stripe timeout caused cascading checkout failure",
  "suspected_root_cause": "payment-service suffered GatewayTimeoutException contacting upstream Stripe API",
  "confidence_score": 0.95,
  "recommended_actions": ["Increase circuit breaker timeout", "Failover to Adyen"],
  "evidence": [
    {
      "evidence_type": "LOG",
      "reference_id": "log-payment-001",
      "service": "payment-service",
      "excerpt": "GatewayTimeoutException: Stripe timed out after 8000ms"
    }
  ]
}
```""",
        tool_calls=[],
    )

    fallback = DeterministicFallbackEngine()
    engine = InvestigationEngine(
        llm_client=mock_llm, fallback_engine=fallback, db_manager=inv_db
    )
    report = await engine.investigate_incident(incident)

    # 4. Verify AI report
    assert report.status == InvestigationStatus.COMPLETED
    assert not report.is_fallback
    assert report.confidence_score == 0.95
    assert "payment-service" in report.suspected_root_cause
    assert len(report.evidence) == 1
    assert report.evidence[0].evidence_type == EvidenceType.LOG
    assert report.evidence[0].reference_id == "log-payment-001"

    # 5. Verify database persistence
    saved_report = await inv_db.get_report_by_incident(incident.incident_id)
    assert saved_report is not None
    assert saved_report.confidence_score == 0.95

    await corr_db.close()
    await inv_db.close()


@pytest.mark.asyncio
async def test_full_pipeline_fallback_on_llm_timeout():
    now = datetime.now(UTC)
    logs, _ = generate_payment_timeout_scenario(tenant_id="acme", base_time=now)

    corr_db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await corr_db.ensure_tables()
    mock_es = AsyncMock()
    corr_engine = CorrelationEngine(es_service=mock_es, db_manager=corr_db)
    incidents = await corr_engine.correlate_logs("acme", logs)
    incident = incidents[0]

    inv_db = InvestigationDatabaseManager("sqlite+aiosqlite:///:memory:")
    await inv_db.ensure_tables()

    # Simulate LLM raising timeout
    mock_llm = AsyncMock()
    mock_llm.chat_completion.side_effect = TimeoutError("OpenRouter request timed out after 15s")

    engine = InvestigationEngine(
        llm_client=mock_llm, fallback_engine=DeterministicFallbackEngine(), db_manager=inv_db
    )
    report = await engine.investigate_incident(incident)

    # Verify degraded fallback report was produced cleanly
    assert report.status == InvestigationStatus.DEGRADED_FALLBACK
    assert report.is_fallback is True
    assert report.confidence_score == 0.50
    assert "payment-service" in report.suspected_root_cause
    assert len(report.evidence) >= 1

    await corr_db.close()
    await inv_db.close()
