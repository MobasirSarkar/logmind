# Service 3: Incident Detection & Correlation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic incident detection and correlation engine that evaluates Elasticsearch error spikes across sliding windows, reconstructs causal trace timelines, merges cascading failures via a service dependency graph, and persists stateful incidents in PostgreSQL with a REST API.

**Architecture:** A sliding-window detector calculates error-rate surges against historical baselines; a trace sequencer separates root-cause triggers from cascading errors; a directed dependency graph merges upstream symptoms into active downstream incidents; SQLAlchemy 2.0 Async manages persistent storage with SQLite/PostgreSQL; and FastAPI exposes incident querying and topology management endpoints.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0 Async, aiosqlite, asyncpg, Elasticsearch Async client, Pytest, Pytest-asyncio.

## Global Constraints

- **Python 3.12+ Type Safety:** Pyright must pass with 0 errors, 0 warnings.
- **No Unrequested Generics:** Domain models use concrete metadata definitions (`dict[str, object]`).
- **TDD Enforcement:** Red $\to$ Green $\to$ Refactor cycle on every task.
- **Deterministic Pipeline:** Zero LLM dependencies in detection, correlation, or trace assembly.
- **Dual DB Dialect:** PostgreSQL (`asyncpg`) for live production/Docker, in-memory SQLite (`aiosqlite`) for tests.
- **Surgical Changes:** All new functionality resides under `correlation/` and `tests/correlation/`, with clean mounting in `app/main.py`.

---

### Task 1: Dependencies & Database Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`
- Modify: `app/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `Settings`
- Produces: `DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"` in `Settings`, SQLAlchemy and async DB drivers in dependencies.

- [ ] **Step 1: Write failing test for database configuration**

```python
# In tests/unit/test_config.py:
def test_database_url_config():
    from app.config import Settings
    custom = Settings(DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/logmind")
    assert custom.DATABASE_URL == "postgresql+asyncpg://user:pass@localhost:5432/logmind"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -k test_database_url_config`
Expected: FAIL with attribute error or validation error on Settings.

- [ ] **Step 3: Add dependencies and update configuration**

In `pyproject.toml`:
Add `"sqlalchemy>=2.0.35"`, `"asyncpg>=0.29.0"`, `"aiosqlite>=0.20.0"` to `dependencies`.

In `app/config.py`:
Add `DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"` to `Settings`.

In `docker-compose.yml`:
Add `postgres` service with `image: postgres:16-alpine`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -k test_database_url_config`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright app/config.py`
Expected: 0 errors.

---

### Task 2: Domain Models & Enums

**Files:**
- Create: `correlation/models.py`
- Create: `correlation/__init__.py`
- Test: `tests/correlation/unit/test_correlation_models.py`

**Interfaces:**
- Consumes: Standard library Pydantic v2
- Produces: `IncidentSeverity`, `IncidentStatus`, `EventType`, `DependencyType`, `ServiceNode`, `ServiceDependency`, `IncidentEvent`, `Incident`.

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_correlation_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_correlation_models.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'correlation'`

- [ ] **Step 3: Implement domain models in `correlation/models.py`**

```python
import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"

class EventType(str, Enum):
    INITIAL_ERROR = "INITIAL_ERROR"
    CASCADING_ERROR = "CASCADING_ERROR"
    TIMEOUT = "TIMEOUT"
    GATEWAY_5XX = "GATEWAY_5XX"
    RECOVERY = "RECOVERY"

class DependencyType(str, Enum):
    HTTP = "HTTP"
    DATABASE = "DATABASE"
    CACHE = "CACHE"
    MESSAGE_QUEUE = "MESSAGE_QUEUE"
    GRPC = "GRPC"

class ServiceNode(BaseModel):
    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    name: str
    environment: str = "production"

class ServiceDependency(BaseModel):
    dependency_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    source_service: str
    target_service: str
    dependency_type: DependencyType = DependencyType.HTTP

class IncidentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    timestamp: datetime
    service: str
    event_type: EventType
    error_signature: str | None = None
    trace_id: str | None = None
    log_id: str | None = None
    message: str

class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.DETECTED
    started_at: datetime
    resolved_at: datetime | None = None
    trigger_service: str
    trigger_signature: str | None = None
    affected_services: list[str] = Field(default_factory=list)
    events: list[IncidentEvent] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_correlation_models.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/models.py`
Expected: 0 errors.

---

### Task 3: Database Layer & Relational Schema

**Files:**
- Create: `correlation/db.py`
- Test: `tests/correlation/unit/test_db.py`

**Interfaces:**
- Consumes: `app.config.settings.DATABASE_URL`, `correlation.models`
- Produces: `DatabaseManager`, `ensure_tables()`, `get_session()`, SQLAlchemy ORM tables (`ServiceORM`, `ServiceDependencyORM`, `IncidentORM`, `IncidentEventORM`).

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_db.py
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

    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_db.py`
Expected: FAIL with `ImportError: cannot import name 'DatabaseManager'`

- [ ] **Step 3: Implement SQLAlchemy Async engine and repository in `correlation/db.py`**

Implement `correlation/db.py` with:
- Declarative Base with mapped columns for `services`, `service_dependencies`, `incidents`, `incident_events`.
- JSON serialization for `affected_services` and `metadata`.
- `DatabaseManager` providing `ensure_tables()`, `save_dependency()`, `get_dependencies()`, `save_incident()`, `get_incident()`, `list_incidents()`, `update_incident_status()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_db.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/db.py`
Expected: 0 errors.

---

### Task 4: Error-Rate Spike Detector

**Files:**
- Create: `correlation/detector.py`
- Test: `tests/correlation/unit/test_spike_detector.py`

**Interfaces:**
- Consumes: `ElasticsearchService`
- Produces: `SpikeDetector.evaluate_window(tenant_id: str, lookback_seconds: int = 60) -> list[SpikeAlert]`

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_spike_detector.py
from unittest.mock import AsyncMock
import pytest
from correlation.detector import SpikeAlert, SpikeDetector

@pytest.mark.asyncio
async def test_spike_detector_triggers_on_surge():
    mock_es = AsyncMock()
    detector = SpikeDetector(es_client=mock_es)

    # Return error counts: current window (15 errors out of 50 requests = 0.30)
    # Baseline window (1 error out of 100 requests = 0.01)
    mock_es.count.side_effect = [
        {"count": 15},  # current errors
        {"count": 50},  # current total
        {"count": 1},   # baseline errors
        {"count": 100}, # baseline total
    ]

    spikes = await detector.evaluate_service(tenant_id="t-1", service="payment-service")
    assert len(spikes) == 1
    assert spikes[0].service == "payment-service"
    assert spikes[0].error_count == 15
    assert spikes[0].error_rate == pytest.approx(0.30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_spike_detector.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `SpikeDetector` in `correlation/detector.py`**

Implement spike evaluation math from Section 4.1:
- Threshold: Current error rate $\ge 3\times$ baseline or $> 0.05$ with count $\ge 10$.
- Returns structured `SpikeAlert` instances.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_spike_detector.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/detector.py`
Expected: 0 errors.

---

### Task 5: Trace Timeline Reconstruction & Root Cause Sequencer

**Files:**
- Create: `correlation/trace_sequencer.py`
- Test: `tests/correlation/unit/test_trace_sequencer.py`

**Interfaces:**
- Consumes: `list[RawLogPayload]`
- Produces: `TraceSequencer.sequence_trace(logs: list[RawLogPayload]) -> tuple[IncidentEvent, list[IncidentEvent]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_trace_sequencer.py
from datetime import UTC, datetime, timedelta
from correlation.models import EventType
from correlation.trace_sequencer import TraceSequencer

def test_trace_sequencer_isolates_initial_trigger():
    t0 = datetime.now(UTC)
    logs = [
        {
            "timestamp": (t0 + timedelta(milliseconds=10)).isoformat(),
            "level": "ERROR",
            "message": "GatewayTimeoutException: Stripe timed out",
            "context": {"service": "payment-service", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-3", "parent_span_id": "sp-2"},
        },
        {
            "timestamp": (t0 + timedelta(milliseconds=20)).isoformat(),
            "level": "ERROR",
            "message": "OrderProcessingError: payment failed",
            "context": {"service": "order-service", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-2", "parent_span_id": "sp-1"},
        },
        {
            "timestamp": (t0 + timedelta(milliseconds=30)).isoformat(),
            "level": "ERROR",
            "message": "BadGateway: downstream error",
            "context": {"service": "api-gateway", "tenant_id": "t-1"},
            "trace": {"trace_id": "tr-100", "span_id": "sp-1", "parent_span_id": None},
        },
    ]

    sequencer = TraceSequencer()
    initial_event, cascading_events = sequencer.sequence_trace("inc-1", logs)

    assert initial_event.service == "payment-service"
    assert initial_event.event_type == EventType.INITIAL_ERROR
    assert len(cascading_events) == 2
    assert cascading_events[0].service == "order-service"
    assert cascading_events[0].event_type == EventType.CASCADING_ERROR
    assert cascading_events[1].service == "api-gateway"
    assert cascading_events[1].event_type == EventType.CASCADING_ERROR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_trace_sequencer.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `TraceSequencer` in `correlation/trace_sequencer.py`**

Sorts log items chronologically by parsed timestamp, marks the earliest error as `EventType.INITIAL_ERROR`, and all subsequent upstream errors as `EventType.CASCADING_ERROR`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_trace_sequencer.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/trace_sequencer.py`
Expected: 0 errors.

---

### Task 6: Dependency Graph & Incident Merging Logic

**Files:**
- Create: `correlation/graph.py`
- Test: `tests/correlation/unit/test_dependency_merger.py`

**Interfaces:**
- Consumes: `ServiceDependency`, `Incident`
- Produces: `DependencyGraph.find_active_downstream_incident(tenant_id: str, service: str, active_incidents: list[Incident]) -> Incident | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_dependency_merger.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_dependency_merger.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `DependencyGraph` in `correlation/graph.py`**

Builds an in-memory adjacency list of service dependencies. Traverses downstream paths to identify active incidents within threshold.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_dependency_merger.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/graph.py`
Expected: 0 errors.

---

### Task 7: Correlation Engine Orchestrator

**Files:**
- Create: `correlation/engine.py`
- Test: `tests/correlation/unit/test_engine.py`

**Interfaces:**
- Consumes: `SpikeDetector`, `TraceSequencer`, `DependencyGraph`, `DatabaseManager`, `ElasticsearchService`
- Produces: `CorrelationEngine.evaluate_tenant(tenant_id: str) -> list[Incident]`

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/unit/test_engine.py
from unittest.mock import AsyncMock
import pytest
from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine

@pytest.mark.asyncio
async def test_correlation_engine_orchestrates_detection():
    mock_es = AsyncMock()
    db = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    engine = CorrelationEngine(es_service=mock_es, db_manager=db)
    # Stub detector, graph, and ES responses to simulate evaluation pass
    incidents = await engine.evaluate_tenant(tenant_id="t-1")
    assert isinstance(incidents, list)

    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/unit/test_engine.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `CorrelationEngine` in `correlation/engine.py`**

Orchestrates:
1. Fetching topology dependencies from DB into `DependencyGraph`.
2. Running `SpikeDetector` across active services.
3. Grouping logs by `trace_id` and running `TraceSequencer`.
4. Merging cascading errors via `DependencyGraph`.
5. Persisting new or updated incidents to `DatabaseManager`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/unit/test_engine.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/engine.py`
Expected: 0 errors.

---

### Task 8: HTTP API & Lifespan Integration

**Files:**
- Create: `correlation/api.py`
- Modify: `app/main.py`
- Test: `tests/correlation/integration/test_incident_api.py`

**Interfaces:**
- Consumes: `CorrelationEngine`, `DatabaseManager`
- Produces: Router mounted at `/api/v1/incidents` and `/api/v1/topology`.

- [ ] **Step 1: Write the failing test**

```python
# tests/correlation/integration/test_incident_api.py
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import create_app

@pytest.mark.asyncio
async def test_incident_api_list_and_topology():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get(
            "/api/v1/incidents",
            headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "items" in body["data"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/correlation/integration/test_incident_api.py`
Expected: FAIL with 404 Not Found.

- [ ] **Step 3: Implement endpoints in `correlation/api.py` and mount in `app/main.py`**

Implement endpoints:
- `GET /api/v1/incidents`
- `GET /api/v1/incidents/{incident_id}`
- `POST /api/v1/incidents/evaluate`
- `PATCH /api/v1/incidents/{incident_id}/status`
- `GET /api/v1/topology`
- `POST /api/v1/topology/dependencies`

Mount `correlation_router` in `app/main.py` and hook database setup/teardown in `lifespan`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/correlation/integration/test_incident_api.py`
Expected: PASS

- [ ] **Step 5: Verify Pyright**

Run: `uv run pyright correlation/api.py app/main.py`
Expected: 0 errors.

---

### Task 9: End-to-End Incident Pipeline Verification

**Files:**
- Create: `tests/correlation/integration/test_end_to_end_detection.py`

**Interfaces:**
- Consumes: Simulator incident generator (`generate_payment_timeout_scenario`), Ingestion pipeline (`bulk_index`), Correlation Engine (`evaluate_tenant`).
- Produces: Complete proof that a synthetic incident is ingested, evaluated, correlated, and persisted with single root-cause isolation.

- [ ] **Step 1: Write the end-to-end integration test**

```python
# tests/correlation/integration/test_end_to_end_detection.py
from datetime import UTC, datetime
from unittest.mock import AsyncMock
import pytest
from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine
from correlation.models import DependencyType, EventType, ServiceDependency
from simulator.scenarios import generate_payment_timeout_scenario

@pytest.mark.asyncio
async def test_end_to_end_payment_timeout_correlation():
    db = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    # 1. Register topology: api-gateway -> order-service -> payment-service
    await db.save_dependency(ServiceDependency(tenant_id="acme", source_service="api-gateway", target_service="order-service", dependency_type=DependencyType.HTTP))
    await db.save_dependency(ServiceDependency(tenant_id="acme", source_service="order-service", target_service="payment-service", dependency_type=DependencyType.HTTP))

    # 2. Generate synthetic incident logs
    now = datetime.now(UTC)
    logs, ground_truth = generate_payment_timeout_scenario(tenant_id="acme", base_time=now)

    # 3. Wire mock ES service returning synthetic logs for search queries
    mock_es = AsyncMock()
    mock_es.search.return_value = {"hits": {"total": {"value": len(logs)}, "hits": [{"_source": log} for log in logs]}}

    engine = CorrelationEngine(es_service=mock_es, db_manager=db)
    incidents = await engine.correlate_logs(tenant_id="acme", logs=logs)

    # 4. Verify exactly ONE incident was created, rooted in payment-service
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.trigger_service == "payment-service"
    assert "payment-service" in inc.affected_services
    assert "order-service" in inc.affected_services
    assert "api-gateway" in inc.affected_services

    # 5. Verify event categorization
    initial_events = [e for e in inc.events if e.event_type == EventType.INITIAL_ERROR]
    assert len(initial_events) == 1
    assert initial_events[0].service == "payment-service"

    cascading_events = [e for e in inc.events if e.event_type == EventType.CASCADING_ERROR]
    assert len(cascading_events) >= 2

    await db.close()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/correlation/integration/test_end_to_end_detection.py -v`
Expected: PASS

- [ ] **Step 3: Run full workspace test suite and Pyright**

Run: `uv run pyright`
Expected: 0 errors.

Run: `uv run pytest`
Expected: All tests pass.
