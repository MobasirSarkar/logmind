# LogMind — Service 2: Synthetic Incident Simulator & Mock Log Generator Design

**Date:** 2026-09-04  
**Author:** LogMind Team  
**Status:** Approved for Implementation  
**Scope:** Service 2 of LogMind Distributed Architecture  

---

## 1. Executive Summary

In distributed systems observability, validating incident correlation and AI-assisted root-cause analysis is hindered by the unpredictability of production outages. **Service 2: Synthetic Incident Simulator & Mock Log Generator** solves this by providing a deterministic, reproducible, multi-service traffic and failure generator.

Service 2 simulates a realistic 5-node microservices architecture (`api-gateway`, `auth-service`, `order-service`, `payment-service`, `notification-service`), synthesizes realistic distributed traces across inter-service calls, generates steady-state background traffic, and provides on-demand failure injection for the 4 canonical incident patterns defined in LogMind's system context:
1. Payment Provider Timeout
2. Database Connection Pool Exhaustion
3. Authentication Dependency Failure
4. Retry Storm with Request Amplification

Each simulation run generates a structured ground-truth metadata record (`ScenarioRunRecord`), enabling automated evaluation and scoring of the downstream AI Investigation Engine. The service is accessible via an HTTP Control API and a command-line interface (CLI).

---

## 2. Architecture & Call Graph Topology

```text
┌─────────────────────────────────────────────────────────────┐
│                 Synthetic Incident Simulator                │
│                                                             │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │   HTTP Control API    │       │     CLI Runner        │  │
│  │ /api/v1/simulator/... │       │  python -m simulator  │  │
│  └───────────┬───────────┘       └───────────┬───────────┘  │
│              └───────────────┬───────────────┘              │
│                              ▼                              │
│                 ┌─────────────────────────┐                 │
│                 │ Simulation State Engine │                 │
│                 │ (Idle / Steady / Active)│                 │
│                 └────────────┬────────────┘                 │
│                              ▼                              │
│                 ┌─────────────────────────┐                 │
│                 │ Service Topology Graph  │                 │
│                 │ (Call Chain Simulation) │                 │
│                 └────────────┬────────────┘                 │
│                              ▼                              │
│                 ┌─────────────────────────┐                 │
│                 │ Async Log Batch Shipper │                 │
│                 │ (HTTP Client to Svc 1)  │                 │
│                 └────────────┬────────────┘                 │
└──────────────────────────────┼──────────────────────────────┘
                               │ POST /api/v1/logs/ingest
                               ▼
            Service 1: Log Ingestion & Query Platform
```

### Simulated Microservices Topology
The simulator models a canonical e-commerce distributed system:

```text
               ┌─────────────────┐
               │   api-gateway   │
               └────────┬────────┘
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
┌─────────────────┐           ┌─────────────────┐
│  auth-service   │           │  order-service  │
└─────────────────┘           └────────┬────────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
               ┌─────────────────┐           ┌──────────────────────┐
               │ payment-service │           │ notification-service │
               └─────────────────┘           └──────────────────────┘
```

1. **`api-gateway`:** Ingress router, authenticates with `auth-service`, forwards orders to `order-service`.
2. **`auth-service`:** Validates sessions, handles tokens; depends on an internal session cache/datastore.
3. **`order-service`:** Coordinates transactional order creation, manages relational DB transactions, calls payment and notifications.
4. **`payment-service`:** Integrates with downstream payment gateways (e.g. Stripe mock).
5. **`notification-service`:** Dispatches order confirmation webhooks and emails.

---

## 3. Domain Models & Type Safety

All models are implemented using Pydantic v2 with strict enums and generic metadata:

```python
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

# --- Enums ---

class ServiceName(str, Enum):
    API_GATEWAY = "api-gateway"
    AUTH_SERVICE = "auth-service"
    ORDER_SERVICE = "order-service"
    PAYMENT_SERVICE = "payment-service"
    NOTIFICATION_SERVICE = "notification-service"

class ScenarioType(str, Enum):
    PAYMENT_TIMEOUT = "PAYMENT_TIMEOUT"
    DB_POOL_EXHAUSTION = "DB_POOL_EXHAUSTION"
    AUTH_DEPENDENCY_FAILURE = "AUTH_DEPENDENCY_FAILURE"
    RETRY_STORM = "RETRY_STORM"

class SimulationStatus(str, Enum):
    IDLE = "IDLE"
    STEADY_STATE = "STEADY_STATE"
    INJECTING_FAILURE = "INJECTING_FAILURE"
    DRAINING = "DRAINING"

# --- Generics ---

TScenarioMeta = TypeVar("TScenarioMeta", default=Dict[str, Any])

# --- Control & Ground Truth Models ---

class ScenarioRunRecord(BaseModel, Generic[TScenarioMeta]):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario_type: ScenarioType
    tenant_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    root_cause_service: ServiceName
    root_cause_error: str
    affected_services: List[ServiceName]
    expected_diagnosis: str
    total_logs_emitted: int = 0
    scenario_metadata: TScenarioMeta = Field(default_factory=dict)

class StartSimulationRequest(BaseModel):
    tenant_id: str = "tenant-default"
    rate_per_sec: int = Field(default=20, ge=1, le=500)

class TriggerScenarioRequest(BaseModel):
    scenario_type: ScenarioType
    tenant_id: str = "tenant-default"
    duration_seconds: int = Field(default=30, ge=5, le=300)
    intensity: float = Field(default=1.0, ge=0.1, le=5.0)

class SimulationStatusResponse(BaseModel):
    status: SimulationStatus
    tenant_id: str
    current_rate: int
    active_scenario: Optional[ScenarioType] = None
    active_run_id: Optional[str] = None
```

---

## 4. Distributed Tracing & Propagation Engine

For every synthetic request:
1. **Trace Inception:** A unique `trace_id` (UUIDv4) is minted at the `api-gateway`.
2. **Context Propagation:**
   - Gateway creates Root Span (`span_id = S1`, `parent_span_id = None`).
   - Order Service creates Child Span (`span_id = S2`, `parent_span_id = S1`).
   - Payment Service creates Child Span (`span_id = S3`, `parent_span_id = S2`).
3. **Timestamp Consistency:** Child span timestamps start after parent request dispatch, incorporating simulated network latency (5ms–35ms).
4. **Failure Propagation:** When a leaf node fails (e.g. `payment-service`), it logs an `ERROR` with its `trace_id`. The caller (`order-service`) catches the failure, logs a cascading error referencing the identical `trace_id`, and `api-gateway` finishes the trace with an HTTP 500 error log.

---

## 5. Scenario Implementation Specifications

### 5.1 Scenario 1: Payment Provider Timeout
* **Mechanism:** Simulates third-party payment API latency increasing from 150ms to 8,000ms.
* **Failure Cascade:**
  1. `payment-service` throws `GatewayTimeoutException: Stripe upstream timed out after 8000ms` (HTTP 504).
  2. `order-service` captures timeout, emits `OrderProcessingError: payment authorization failed for order <ID>` (HTTP 502).
  3. `api-gateway` emits `BadGateway: downstream order-service returned 502` (HTTP 500).
* **Expected Ground Truth:**
  - `root_cause_service`: `payment-service`
  - `expected_diagnosis`: `"Payment provider timeout in payment-service caused cascading order creation failures in order-service and HTTP 500 responses at api-gateway."`

### 5.2 Scenario 2: Database Connection Pool Exhaustion
* **Mechanism:** Simulates an unindexed database query locking table rows in `order-service`.
* **Failure Cascade:**
  1. Connection pool active count hits threshold (20/20).
  2. `order-service` emits `ConnectionPoolExhausted: HikariPool-1 - Connection is not available, request timed out after 30000ms`.
  3. Database query queues back up; incoming API requests timeout with 503 Service Unavailable.
  4. `api-gateway` logs widespread 5xx errors.
* **Expected Ground Truth:**
  - `root_cause_service`: `order-service`
  - `expected_diagnosis`: `"Database connection pool exhaustion in order-service caused connection timeouts and downstream request drops."`

### 5.3 Scenario 3: Authentication Dependency Failure
* **Mechanism:** Simulates network partitioning or process crash of the Redis session cache used by `auth-service`.
* **Failure Cascade:**
  1. `auth-service` emits `FATAL`: `RedisConnectionRefused: Error connecting to session cache at redis:6379`.
  2. `auth-service` rejects token validation requests.
  3. `api-gateway` drops user traffic with `401 Unauthorized` and logs internal authentication failures.
* **Expected Ground Truth:**
  - `root_cause_service`: `auth-service`
  - `expected_diagnosis`: `"Session cache connectivity failure in auth-service prevented authentication token verification, causing gateway request rejections."`

### 5.4 Scenario 4: Retry Storm with Request Amplification
* **Mechanism:** Simulates transient 500ms network blip in `notification-service`.
* **Failure Cascade:**
  1. Notification webhook times out.
  2. `order-service` executes 5 aggressive retries in a tight loop with zero exponential backoff or jitter.
  3. Ingress volume into `notification-service` increases 5x, saturating CPU and worker threads.
  4. Cascading saturation causes total failure across all notification delivery queues.
* **Expected Ground Truth:**
  - `root_cause_service`: `notification-service`
  - `expected_diagnosis`: `"Aggressive unjittered retries from order-service caused request amplification and thread saturation in notification-service following a transient timeout."`

---

## 6. Control Interface (HTTP & CLI)

### 6.1 HTTP Control API Endpoints
* `POST /api/v1/simulator/start` — Start continuous background traffic (accepts `rate_per_sec`, `tenant_id`).
* `POST /api/v1/simulator/stop` — Halts all active traffic generation.
* `POST /api/v1/simulator/scenarios/trigger` — Injects a failure scenario (accepts `scenario_type`, `duration_seconds`, `intensity`).
* `GET /api/v1/simulator/status` — Returns current engine status and active scenario.
* `GET /api/v1/simulator/runs/{run_id}` — Retrieves the ground-truth metadata record for verification and benchmark scoring.

### 6.2 CLI Runner
The CLI operates as a convenient developer tool:
```bash
# Start steady-state traffic at 25 logs/sec
python -m simulator start --rate 25

# Inject a database pool exhaustion incident for 45 seconds
python -m simulator trigger --scenario DB_POOL_EXHAUSTION --duration 45

# View active status
python -m simulator status
```

---

## 7. Test-Driven Development (TDD) Strategy

### 7.1 Test Suites Structure
```text
tests/simulator/
├── unit/
│   ├── test_simulator_models.py       # Pydantic models, Enums, validation
│   ├── test_trace_generator.py        # Distributed trace hierarchy & span creation
│   ├── test_scenario_payment.py       # Payment timeout failure cascade generator
│   ├── test_scenario_db_pool.py       # DB pool exhaustion log cascade generator
│   ├── test_scenario_auth_fail.py     # Auth session cache crash generator
│   └── test_scenario_retry_storm.py   # Retry amplification generator
└── integration/
    ├── test_simulator_api.py          # HTTP control endpoints (start, stop, trigger)
    ├── test_shipper_integration.py    # Verify synthetic logs match Service 1 schema and reach /ingest
    └── test_ground_truth_capture.py   # Verify ScenarioRunRecord matches emitted logs
```

### 7.2 TDD Implementation Sequence
1. **Phase 1: Domain Models & Topology (Unit TDD)**
   - Test: Write failing tests verifying `ServiceName`, `ScenarioType`, `SimulationStatus`, and `ScenarioRunRecord`.
   - Code: Implement models in `simulator/models.py`.
2. **Phase 2: Trace Generator (Unit TDD)**
   - Test: Write failing tests asserting parent-child span nesting, sequential timestamps, and trace propagation.
   - Code: Implement `simulator/trace.py`.
3. **Phase 3: Scenario Generators (Unit TDD)**
   - Test: Write failing tests asserting that each scenario function generates the exact sequence of error logs with consistent trace IDs.
   - Code: Implement `simulator/scenarios/*.py`.
4. **Phase 4: Async Shipper & Control API (Integration TDD)**
   - Test: Write failing test verifying `POST /api/v1/simulator/scenarios/trigger` emits batches to mock Service 1 `/ingest` endpoint and returns `ScenarioRunRecord`.
   - Code: Implement `simulator/api.py` and `simulator/shipper.py`.

---

## 8. Definition of Done for Service 2

1. All unit and integration test suites pass with 100% green status via `pytest`.
2. Simulator generates clean steady-state traffic and ships batches to Service 1 without schema errors.
3. All 4 incident scenarios execute on demand via HTTP and CLI, creating accurate cascading error logs with shared trace IDs.
4. Each scenario run persists a `ScenarioRunRecord` with ground-truth root cause labels for downstream AI benchmark validation.
