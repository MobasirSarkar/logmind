from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from correlation.models import Incident, IncidentSeverity, IncidentStatus
from investigation.client import (
    ChatCompletionResponse,
    ToolCall,
    ToolCallFunction,
)
from investigation.engine import InvestigationEngine
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import EvidenceType, InvestigationStatus
from investigation.tools import InvestigationToolbox


@pytest.mark.asyncio
async def test_llm_tool_loop_executes_tool_and_produces_diagnosis():
    # 1. Turn 1: LLM requests search_logs; Turn 2: LLM returns final diagnosis
    mock_llm = AsyncMock()
    mock_llm.chat_completion.side_effect = [
        ChatCompletionResponse(
            content="I will search logs for payment errors.",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    type="function",
                    function=ToolCallFunction(
                        name="search_logs", arguments='{"query": "Stripe timeout"}'
                    ),
                )
            ],
        ),
        ChatCompletionResponse(
            content="""```json
{
  "summary": "Stripe upstream payment timeout caused cascade",
  "suspected_root_cause": "payment-service suffered GatewayTimeoutException contacting Stripe API",
  "confidence_score": 0.95,
  "recommended_actions": ["Increase Stripe timeout threshold", "Verify webhook retries"],
  "evidence": [
    {
      "evidence_type": "LOG",
      "reference_id": "log-pay-999",
      "service": "payment-service",
      "excerpt": "GatewayTimeoutException: Stripe timed out after 8000ms"
    }
  ]
}
```""",
            tool_calls=[],
        ),
    ]

    # 2. Mock ES returning log for search_logs
    mock_es = AsyncMock()
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_source": {
                        "id": "log-pay-999",
                        "message": "GatewayTimeoutException: Stripe timed out after 8000ms",
                        "level": "ERROR",
                        "context": {"service": "payment-service"},
                    }
                }
            ],
        }
    }

    mock_db = AsyncMock()
    mock_db.get_dependencies.return_value = []
    mock_db.list_incidents.return_value = []

    toolbox = InvestigationToolbox(
        es_service=mock_es, db_manager=mock_db, tenant_id="acme"
    )
    engine = InvestigationEngine(
        llm_client=mock_llm, fallback_engine=DeterministicFallbackEngine()
    )

    incident = Incident(
        incident_id="inc-stripe-1",
        tenant_id="acme",
        title="Payment Service Latency Spike",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=datetime.now(UTC),
        trigger_service="payment-service",
    )

    report = await engine.run_investigation_loop(incident, toolbox=toolbox)

    assert report.status == InvestigationStatus.COMPLETED
    assert not report.is_fallback
    assert report.confidence_score == 0.95
    assert "payment-service" in report.suspected_root_cause

    # Verify tool execution step was recorded
    assert len(report.steps) == 1
    assert report.steps[0].tool_name.value == "search_logs"

    # Verify evidence citations
    assert len(report.evidence) == 1
    assert report.evidence[0].evidence_type == EvidenceType.LOG
    assert report.evidence[0].reference_id == "log-pay-999"
