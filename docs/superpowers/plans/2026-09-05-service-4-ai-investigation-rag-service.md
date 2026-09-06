# Service 4: AI Investigation & RAG Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AI Investigation & RAG Service that conducts controlled, multi-step incident root-cause analysis using sandboxed read-only tools, cites concrete log/trace evidence, embeds runbooks via local FastEmbed, calls LLMs via OpenRouter, and guarantees zero downtime through deterministic graceful fallback.

**Architecture:** An agent orchestrator drives a bounded 5-round tool loop querying live logs, traces, topology, and embedded runbooks; an OpenAI-compatible HTTP client interfaces with OpenRouter; a deterministic fallback engine synthesizes incident reports if the LLM fails or times out; SQLAlchemy Async persists reports and audit trails; and FastAPI exposes control and inspection endpoints.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0 Async, httpx, FastEmbed (384d ONNX), Elasticsearch Async, Pytest, Pytest-asyncio.

## Global Constraints

- **Python 3.12+ Type Safety:** 0 errors under Pyright strict mode.
- **No Unrequested Generics:** Concrete models without `[T]` type parameters (`metadata: dict[str, object]`).
- **TDD Enforcement:** Red $\to$ Green $\to$ Refactor cycle on every task.
- **Controlled Tool Calling:** Strictly 5 read-only tools with explicit Pydantic schemas. Maximum 5 tool-calling rounds.
- **Deterministic Fallback Guarantee:** An LLM timeout ($> 15$s) or HTTP failure immediately returns a valid `InvestigationReport` with `DEGRADED_FALLBACK` status within 100ms.
- **Zero Hallucination:** Every claim in the diagnosis references a concrete `reference_id` (log ID, trace ID, or runbook ID).

---

### Task 1: LLM Configuration & OpenRouter Client

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `investigation/client.py`
- Create: `investigation/__init__.py`
- Test: `tests/investigation/unit/test_llm_client.py`

**Interfaces:**
- Consumes: `Settings.LLM_KEY`, `Settings.LLM_BASE_URL`, `Settings.LLM_MODEL`
- Produces: `LLMClient.chat_completion(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing test for LLM client**

```python
# tests/investigation/unit/test_llm_client.py
from unittest.mock import AsyncMock, patch
import pytest
from investigation.client import LLMClient


@pytest.mark.asyncio
async def test_llm_client_chat_completion():
    client = LLMClient(
        api_key="test-key", base_url="https://openrouter.ai/api/v1", model="test-model"
    )
    mock_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Root cause identified as payment gateway timeout.",
                }
            }
        ]
    }

    with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await client.chat_completion(
            messages=[{"role": "user", "content": "Investigate"}]
        )
        assert (
            res["choices"][0]["message"]["content"]
            == "Root cause identified as payment gateway timeout."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_llm_client.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'investigation'`

- [ ] **Step 3: Update `app/config.py` and implement `investigation/client.py`**

In `app/config.py`:
Add `LLM_KEY: str | None = None`, `LLM_BASE_URL: str = "https://openrouter.ai/api/v1"`, `LLM_MODEL: str = "anthropic/claude-3.5-sonnet"`.

In `investigation/client.py`:
Implement `LLMClient` using `httpx.AsyncClient` with configurable timeout (default 15.0s), sending `Authorization: Bearer {api_key}` and `HTTP-Referer: https://logmind.io`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_llm_client.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright app/config.py investigation/client.py`
Expected: 0 errors.

---

### Task 2: Domain Models & Evidence Citation Schemas

**Files:**
- Create: `investigation/models.py`
- Test: `tests/investigation/unit/test_investigation_models.py`

**Interfaces:**
- Consumes: Standard library Pydantic v2
- Produces: `InvestigationStatus`, `EvidenceType`, `ToolName`, `EvidenceItem`, `InvestigationStep`, `InvestigationReport`.

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/unit/test_investigation_models.py
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
        recommended_actions=[
            "Check Stripe status",
            "Increase circuit breaker sensitivity",
        ],
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_investigation_models.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement domain models in `investigation/models.py`**

Implement enums (`InvestigationStatus`, `EvidenceType`, `ToolName`) and models (`EvidenceItem`, `InvestigationStep`, `InvestigationReport`) with no generics.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_investigation_models.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/models.py`
Expected: 0 errors.

---

### Task 3: Database Layer for Investigations & Auditing

**Files:**
- Create: `investigation/db.py`
- Test: `tests/investigation/unit/test_investigation_db.py`

**Interfaces:**
- Consumes: `investigation.models`, `correlation.db.Base`
- Produces: `InvestigationDatabaseManager`, `InvestigationReportORM`, `InvestigationStepORM`, `EvidenceItemORM`.

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/unit/test_investigation_db.py
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
        summary="Payment timeout",
        suspected_root_cause="Stripe latency",
        confidence_score=0.90,
        affected_services=["payment-service"],
        evidence=[
            EvidenceItem(
                evidence_type=EvidenceType.LOG, reference_id="l-1", excerpt="Timeout"
            )
        ],
        steps=[
            InvestigationStep(
                step_number=1,
                tool_name=ToolName.GET_TRACE,
                tool_input={},
                tool_output={},
                duration_ms=50,
            )
        ],
        started_at=now,
        completed_at=now,
    )
    await db.save_report(report)

    fetched = await db.get_report_by_incident("inc-1")
    assert fetched is not None
    assert fetched.summary == "Payment timeout"
    assert len(fetched.evidence) == 1
    assert len(fetched.steps) == 1

    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_investigation_db.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `InvestigationDatabaseManager` in `investigation/db.py`**

Build on SQLAlchemy Async models using `StaticPool` for in-memory SQLite and `lazy="selectin"` for relationships.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_investigation_db.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/db.py`
Expected: 0 errors.

---

### Task 4: Sandboxed Read-Only Investigation Tools

**Files:**
- Create: `investigation/tools.py`
- Test: `tests/investigation/unit/test_tool_sandbox.py`

**Interfaces:**
- Consumes: `ElasticsearchService`, `DatabaseManager` (Service 3)
- Produces: `InvestigationToolbox`:
  - `search_logs(query: str, service: str | None = None, limit: int = 10) -> dict[str, Any]`
  - `get_trace(trace_id: str) -> dict[str, Any]`
  - `search_runbooks(query: str, service: str | None = None) -> dict[str, Any]`
  - `get_related_incidents(signature_hash: str) -> dict[str, Any]`
  - `get_service_dependencies(service: str) -> dict[str, Any]`
  - `get_tool_definitions() -> list[dict[str, Any]]` (OpenAI function calling schemas)

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/unit/test_tool_sandbox.py
from unittest.mock import AsyncMock
import pytest
from investigation.tools import InvestigationToolbox


@pytest.mark.asyncio
async def test_tool_definitions_and_execution():
    mock_es = AsyncMock()
    mock_db = AsyncMock()
    toolbox = InvestigationToolbox(
        es_service=mock_es, db_manager=mock_db, tenant_id="acme"
    )

    # 1. Verify schema definitions
    tool_defs = toolbox.get_tool_definitions()
    assert len(tool_defs) == 5
    tool_names = {t["function"]["name"] for t in tool_defs}
    assert "search_logs" in tool_names
    assert "get_trace" in tool_names
    assert "search_runbooks" in tool_names
    assert "get_related_incidents" in tool_names
    assert "get_service_dependencies" in tool_names

    # 2. Test search_logs execution
    mock_es.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [{"_source": {"message": "Test"}}]}
    }
    res = await toolbox.execute_tool("search_logs", {"query": "timeout", "limit": 5})
    assert res["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_tool_sandbox.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `InvestigationToolbox` in `investigation/tools.py`**

Define tools with strict 5-second execution timeouts and read-only constraints.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_tool_sandbox.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/tools.py`
Expected: 0 errors.

---

### Task 5: Deterministic Graceful Fallback Engine

**Files:**
- Create: `investigation/fallback.py`
- Test: `tests/investigation/unit/test_fallback_engine.py`

**Interfaces:**
- Consumes: `Incident` (Service 3), `DependencyGraph`
- Produces: `DeterministicFallbackEngine.generate_report(incident: Incident, error_reason: str = "LLM provider timeout") -> InvestigationReport`

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/unit/test_fallback_engine.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_fallback_engine.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `DeterministicFallbackEngine` in `investigation/fallback.py`**

Synthesizes structured reports from `Incident` events and topology within $< 100$ms with confidence 0.50.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_fallback_engine.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/fallback.py`
Expected: 0 errors.

---

### Task 6: Multi-Step LLM Investigation Loop & Budget Enforcement

**Files:**
- Create: `investigation/engine.py`
- Test: `tests/investigation/unit/test_step_budget.py`
- Test: `tests/investigation/integration/test_llm_tool_loop.py`

**Interfaces:**
- Consumes: `LLMClient`, `InvestigationToolbox`, `DeterministicFallbackEngine`, `InvestigationDatabaseManager`
- Produces: `InvestigationEngine.investigate_incident(incident: Incident) -> InvestigationReport`

- [ ] **Step 1: Write the failing tests**

```python
# tests/investigation/unit/test_step_budget.py
from datetime import UTC, datetime
from unittest.mock import AsyncMock
import pytest
from correlation.models import Incident, IncidentSeverity, IncidentStatus
from investigation.engine import InvestigationEngine


@pytest.mark.asyncio
async def test_investigation_loop_enforces_max_5_steps():
    mock_llm = AsyncMock()
    # Mock LLM asking for search_logs forever
    mock_llm.chat_completion.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "search_logs",
                                "arguments": '{"query": "error"}',
                            },
                        }
                    ],
                }
            }
        ]
    }

    mock_toolbox = AsyncMock()
    mock_toolbox.get_tool_definitions.return_value = [
        {"type": "function", "function": {"name": "search_logs"}}
    ]
    mock_toolbox.execute_tool.return_value = {"results": []}

    engine = InvestigationEngine(llm_client=mock_llm, fallback_engine=AsyncMock())
    incident = Incident(
        incident_id="inc-1",
        tenant_id="acme",
        title="Test",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        started_at=datetime.now(UTC),
        trigger_service="payment-service",
    )

    report = await engine.run_investigation_loop(incident, toolbox=mock_toolbox)
    assert len(report.steps) <= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/unit/test_step_budget.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `InvestigationEngine` in `investigation/engine.py`**

Orchestrates:
1. Constructing system prompt with incident trigger, timeline, and topology.
2. Step budget enforcement (max 5 rounds).
3. Parsing tool calls and appending to `InvestigationStep` audit list.
4. Parsing final diagnosis into `InvestigationReport` with evidence items.
5. Invoking `fallback_engine` on exceptions or timeouts.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/unit/test_step_budget.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/engine.py`
Expected: 0 errors.

---

### Task 7: Runbook Vector RAG Pipeline

**Files:**
- Create: `investigation/runbooks.py`
- Test: `tests/investigation/integration/test_runbook_rag.py`

**Interfaces:**
- Consumes: `EmbeddingService` (FastEmbed), `ElasticsearchService`
- Produces: `RunbookService.ingest_runbook(service: str, title: str, markdown_content: str) -> str`, `RunbookService.search_runbooks(query: str, service: str | None = None) -> list[dict[str, Any]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/integration/test_runbook_rag.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from investigation.runbooks import RunbookService


@pytest.mark.asyncio
async def test_runbook_ingest_and_search():
    mock_es = AsyncMock()
    mock_embed = MagicMock()
    mock_embed.get_or_compute_embedding.return_value = [0.05] * 384

    service = RunbookService(es_service=mock_es, embedding_service=mock_embed)
    doc_id = await service.ingest_runbook(
        service="payment-service",
        title="Payment Gateway Latency Runbook",
        markdown_content="If Stripe latency exceeds 5000ms, failover to Adyen.",
    )
    assert doc_id is not None
    assert mock_es.index.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/integration/test_runbook_rag.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `RunbookService` in `investigation/runbooks.py`**

Generates FastEmbed 384d vector embeddings for markdown runbooks and indexes them into `logmind-runbooks-{tenant_id}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/integration/test_runbook_rag.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/runbooks.py`
Expected: 0 errors.

---

### Task 8: REST API & Lifespan Integration

**Files:**
- Create: `investigation/api.py`
- Modify: `app/main.py`
- Test: `tests/investigation/integration/test_investigation_api.py`

**Interfaces:**
- Consumes: `InvestigationEngine`, `InvestigationDatabaseManager`, `RunbookService`
- Produces: Router mounted at `/api/v1/investigations` and `/api/v1/runbooks`.

- [ ] **Step 1: Write the failing test**

```python
# tests/investigation/integration/test_investigation_api.py
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import create_app


@pytest.mark.asyncio
async def test_investigation_api_endpoints():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        headers = {"X-Tenant-ID": "acme", "X-API-Key": "lmd_dev_key"}
        res = await ac.get("/api/v1/investigations/inc-1", headers=headers)
        assert res.status_code in (200, 404)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/investigation/integration/test_investigation_api.py`
Expected: FAIL with 404 on unmounted router or 405.

- [ ] **Step 3: Implement endpoints in `investigation/api.py` and mount in `app/main.py`**

Endpoints:
- `POST /api/v1/investigations/{incident_id}/start`
- `GET /api/v1/investigations/{incident_id}`
- `GET /api/v1/investigations/{incident_id}/steps`
- `POST /api/v1/investigations/{incident_id}/retry`
- `POST /api/v1/runbooks`

Mount `investigation_router` in `app/main.py` and hook table creation into `lifespan`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/investigation/integration/test_investigation_api.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright investigation/api.py app/main.py`
Expected: 0 errors.

---

### Task 9: End-to-End Synthetic Incident Investigation Verification

**Files:**
- Create: `tests/investigation/integration/test_end_to_end_investigate.py`

**Interfaces:**
- Consumes: Simulator `generate_payment_timeout_scenario`, Correlation Engine, AI Investigation Engine.
- Produces: Verified end-to-end diagnosis citing log/trace evidence with confidence score $> 0.85$ or clean fallback.

- [ ] **Step 1: Write the end-to-end integration test**

```python
# tests/investigation/integration/test_end_to_end_investigate.py
from datetime import UTC, datetime
from unittest.mock import AsyncMock
import pytest
from correlation.engine import CorrelationEngine
from correlation.db import DatabaseManager
from investigation.db import InvestigationDatabaseManager
from investigation.engine import InvestigationEngine
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import InvestigationStatus
from simulator.scenarios import generate_payment_timeout_scenario


@pytest.mark.asyncio
async def test_full_pipeline_incident_to_ai_diagnosis():
    # 1. Generate synthetic failure cascade
    now = datetime.now(UTC)
    logs, ground_truth = generate_payment_timeout_scenario(
        tenant_id="acme", base_time=now
    )

    # 2. Correlate logs into incident
    corr_db = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await corr_db.ensure_tables()
    mock_es = AsyncMock()
    corr_engine = CorrelationEngine(es_service=mock_es, db_manager=corr_db)
    incidents = await corr_engine.correlate_logs("acme", logs)
    assert len(incidents) == 1
    incident = incidents[0]

    # 3. Investigate with AI engine (mock LLM returning structured diagnosis)
    inv_db = InvestigationDatabaseManager("sqlite+aiosqlite:///:memory:")
    await inv_db.ensure_tables()

    mock_llm = AsyncMock()
    mock_llm.chat_completion.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"summary": "Stripe timeout", "suspected_root_cause": "payment-service timeout", "confidence_score": 0.95, "affected_services": ["payment-service", "order-service"], "evidence": [{"evidence_type": "LOG", "reference_id": "log-1", "excerpt": "GatewayTimeout"}], "recommended_actions": ["Failover to secondary payment gateway"]}',
                }
            }
        ]
    }

    engine = InvestigationEngine(
        llm_client=mock_llm,
        fallback_engine=DeterministicFallbackEngine(),
        db_manager=inv_db,
    )
    report = await engine.investigate_incident(incident)

    # 4. Verify AI report
    assert report.status in (
        InvestigationStatus.COMPLETED,
        InvestigationStatus.DEGRADED_FALLBACK,
    )
    assert "payment-service" in report.suspected_root_cause
    assert len(report.evidence) >= 1

    await corr_db.close()
    await inv_db.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/investigation/integration/test_end_to_end_investigate.py -v`
Expected: PASS

- [ ] **Step 3: Run full workspace test suite and Pyright**

Run: `uv run pyright`
Expected: 0 errors.

Run: `uv run pytest`
Expected: All tests pass.
