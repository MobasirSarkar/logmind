from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from correlation.models import Incident, IncidentSeverity, IncidentStatus
from investigation.client import ChatCompletionResponse, ToolCall, ToolCallFunction
from investigation.engine import InvestigationEngine
from investigation.fallback import DeterministicFallbackEngine


@pytest.mark.asyncio
async def test_investigation_loop_enforces_max_5_steps():
    mock_llm = AsyncMock()
    # Mock LLM calling search_logs continuously
    mock_llm.chat_completion.return_value = ChatCompletionResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="call-loop",
                type="function",
                function=ToolCallFunction(
                    name="search_logs", arguments='{"query": "error"}'
                ),
            )
        ],
    )

    mock_toolbox = AsyncMock()
    mock_toolbox.get_tool_definitions.return_value = []
    mock_toolbox.execute_tool_by_name.return_value = {"count": 0, "logs": []}

    fallback = DeterministicFallbackEngine()
    engine = InvestigationEngine(llm_client=mock_llm, fallback_engine=fallback)

    incident = Incident(
        incident_id="inc-budget-1",
        tenant_id="acme",
        title="Cascading Timeout",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=datetime.now(UTC),
        trigger_service="payment-service",
    )

    report = await engine.run_investigation_loop(
        incident, toolbox=mock_toolbox, max_steps=5
    )
    # Budget must strictly cap tool execution rounds to 5
    assert len(report.steps) <= 5
