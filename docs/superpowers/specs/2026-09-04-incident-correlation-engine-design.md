# LogMind — Service 3: Incident Detection & Correlation Engine Design

**Date:** 2026-09-04  
**Author:** LogMind Team  
**Status:** Approved for Implementation  
**Scope:** Service 3 of LogMind Distributed Architecture  

---

## 1. Executive Summary

In complex distributed architectures, an outage in a downstream dependency causes an explosion of cascading errors across upstream services. Traditional monitoring fires dozens of isolated alerts for the same root issue.

**Service 3: Incident Detection & Correlation Engine** is the deterministic backbone of LogMind. It observes normalized logs from Service 1, detects abnormal spikes using statistical thresholds, correlates failures across distributed traces and dependency topologies, isolates the earliest abnormal event, and groups related failures into a single cohesive, stateful `Incident` stored in PostgreSQL.

Service 3 does not use LLMs for incident discovery; all detection, trace assembly, and correlation logic is 100% deterministic, testable, and auditable.

---

## 2. Architecture & Component Workflow

```text
┌─────────────────────────┐         ┌─────────────────────────┐
│       FastAPI API       │◄────────┤   Developer / UI        │
│  /api/v1/incidents/...  │         │   (Query & Update)      │
└────────────┬────────────┘         └─────────────────────────┘
             │
             ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│   Correlation Engine    │◄────────┤ Sliding Window Detector │
│ (Trace Sorter & Graph)  │         │ (Reads ES Error Metrics)│
└────────────┬────────────┘         └─────────────────────────┘
             │
             ▼
┌─────────────────────────┐
│   PostgreSQL Datastore  │
│ (Incidents, Events,     │
│  Topology, Runbooks)    │
└─────────────────────────┘
```

### Component Roles
1. **Sliding Window Detector:** Regularly queries Elasticsearch error counts across 1-minute and 5-minute windows, comparing current error ratios to baseline traffic.
2. **Trace Correlation Assembler:** Fetches logs sharing a `trace_id`, builds the directed span execution path, and orders events chronologically to separate the *initial trigger* from *downstream consequences*.
3. **Dependency Graph Traversal:** Reads the registered service adjacency list to evaluate if an upstream service failure is a known symptom of a failing downstream dependency.
4. **PostgreSQL Relational Store:** Stores persistent incidents, chronological event timelines, service topologies, and runbooks.
5. **FastAPI Incident Management Gateway:** Exposes endpoints to query incidents, inspect timelines, and manage service dependency mappings.

---

## 3. Domain Models & Relational Schema

All models use SQLAlchemy 2.0 Async / Pydantic v2 with strict enums and generic metadata:

```python
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

# --- Enums ---

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

# --- Generics ---

TIncidentMeta = TypeVar("TIncidentMeta", default=Dict[str, Any])

# --- Domain Models ---

class ServiceNode(BaseModel):
    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    name: str
    environment: str = "production"

class ServiceDependency(BaseModel):
    dependency_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    source_service: str  # e.g. "order-service"
    target_service: str  # e.g. "payment-service"
    dependency_type: DependencyType = DependencyType.HTTP

class IncidentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    timestamp: datetime
    service: str
    event_type: EventType
    error_signature: Optional[str] = None
    trace_id: Optional[str] = None
    log_id: Optional[str] = None
    message: str

class Incident(BaseModel, Generic[TIncidentMeta]):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.DETECTED
    started_at: datetime
    resolved_at: Optional[datetime] = None
    trigger_service: str
    trigger_signature: Optional[str] = None
    affected_services: List[str] = Field(default_factory=list)
    events: List[IncidentEvent] = Field(default_factory=list)
    metadata: TIncidentMeta = Field(default_factory=dict)
```

---

## 4. Deterministic Detection & Correlation Algorithms

### 4.1 Error-Rate Spike Detection Math
The detector calculates the error ratio over a sliding window $W_{\text{current}}$ (60 seconds) and compares it against baseline window $W_{\text{baseline}}$ (10 minutes):

$$\text{ErrorRate}_{\text{current}} = \frac{\text{Count}(\text{Level} \in \{\text{ERROR, FATAL}\})}{\text{Count}(\text{Total Requests})}$$

A spike is flagged when all three criteria are satisfied:
1. $\text{ErrorRate}_{\text{current}} \ge 3 \times \text{ErrorRate}_{\text{baseline}}$ (or $\text{ErrorRate}_{\text{current}} > 0.05$ if baseline is near zero).
2. $\text{ErrorCount}_{\text{current}} \ge 10$ (prevents single-request anomalies from triggering incidents).
3. Spike persists across at least two consecutive 15-second evaluation cycles.

### 4.2 Trace Timeline Reconstruction
When an incident is flagged:
1. All logs matching the incident time window with status codes $\ge 500$ or levels $\in \{\text{ERROR, FATAL}\}$ are fetched.
2. Distinct `trace_id` values are extracted.
3. For each `trace_id`, all logs across all services are ordered strictly by timestamp.
4. **Earliest Abnormal Event Isolation:**
   - The chronologically first `ERROR` log in the trace chain is marked as `EventType.INITIAL_ERROR`.
   - All subsequent errors in upstream calling services on the same `trace_id` are classified as `EventType.CASCADING_ERROR`.

### 4.3 Dependency-Aware Incident Merging
To prevent alert storms:
1. The engine builds an in-memory directed graph of `service_dependencies`.
2. When a service (e.g. `order-service`) experiences a spike, the engine checks if any direct downstream dependency (e.g. `payment-service`) is currently the subject of an `ACTIVE` incident.
3. If an active downstream incident exists within a 120-second threshold, the upstream errors are appended to the existing incident's event log as cascading symptoms, rather than creating a new duplicate incident.

---

## 5. PostgreSQL Schema Definition (DDL)

```sql
CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    environment VARCHAR(64) DEFAULT 'production',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, name, environment)
);

CREATE TABLE service_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    source_service VARCHAR(128) NOT NULL,
    target_service VARCHAR(128) NOT NULL,
    dependency_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, source_service, target_service)
);

CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(32) DEFAULT 'DETECTED',
    started_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    trigger_service VARCHAR(128) NOT NULL,
    trigger_signature VARCHAR(128),
    affected_services JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE incident_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    service VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    error_signature VARCHAR(128),
    trace_id VARCHAR(128),
    log_id VARCHAR(128),
    message TEXT NOT NULL
);

CREATE INDEX idx_incidents_tenant_status ON incidents (tenant_id, status);
CREATE INDEX idx_incident_events_incident_ts ON incident_events (incident_id, timestamp ASC);
```

---

## 6. HTTP API Specification

* `GET /api/v1/incidents` — Lists incidents filtered by `status`, `severity`, `service`, and date range.
* `GET /api/v1/incidents/{incident_id}` — Retrieves full incident record including the complete chronological event timeline.
* `POST /api/v1/incidents/evaluate` — Triggers an on-demand evaluation cycle over a specified time window (used by tests and manual audits).
* `PATCH /api/v1/incidents/{incident_id}/status` — Updates status (`INVESTIGATING`, `MITIGATED`, `RESOLVED`).
* `GET /api/v1/topology` — Retrieves current dependency graph for visualization.
* `POST /api/v1/topology/dependencies` — Registers inter-service dependencies.

---

## 7. Test-Driven Development (TDD) Strategy

### 7.1 Test Suites Structure
```text
tests/correlation/
├── unit/
│   ├── test_correlation_models.py     # Pydantic models, Enums, Generics
│   ├── test_spike_detector.py         # Spike calculation math with edge-case baselines
│   ├── test_trace_sequencer.py        # Chronological ordering and root-cause classification
│   └── test_dependency_merger.py      # Graph traversal and multi-service incident merging
└── integration/
    ├── test_db_persistence.py         # SQLAlchemy asyncpg CRUD with PostgreSQL
    ├── test_incident_api.py           # REST endpoints (/incidents, /topology)
    └── test_end_to_end_detection.py   # Ingest synthetic failure -> evaluate -> assert incident created
```

### 7.2 TDD Implementation Sequence
1. **Phase 1: Domain Models & Enums (Unit TDD)**
   - Test: Validate `IncidentSeverity`, `IncidentStatus`, `EventType`, `DependencyType`.
   - Code: Implement in `correlation/models.py`.
2. **Phase 2: Spike Detection & Trace Sequencing (Unit TDD)**
   - Test: Write failing tests asserting spike detection thresholds and trace event ordering.
   - Code: Implement `correlation/detector.py` and `correlation/trace_sequencer.py`.
3. **Phase 3: Dependency Graph & Merging Logic (Unit TDD)**
   - Test: Write failing tests asserting that an order-service error merges into an active payment-service incident.
   - Code: Implement `correlation/graph.py`.
4. **Phase 4: PostgreSQL Persistence & API (Integration TDD)**
   - Test: Write failing test verifying incident and event insertion via SQLAlchemy asyncpg.
   - Code: Implement `correlation/db.py` and `correlation/api.py`.

---

## 8. Definition of Done for Service 3

1. All unit and integration test suites pass with 100% green status via `pytest`.
2. When Service 2 triggers `PAYMENT_TIMEOUT`, Service 3 accurately isolates `payment-service` as the initial trigger and marks `order-service` and `api-gateway` as cascading consequences.
3. No duplicate incidents are created for correlated downstream failures.
4. Incident timelines are persisted in PostgreSQL with complete trace references and exposed via the REST API.
