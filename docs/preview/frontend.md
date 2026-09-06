# LogMind Frontend Product and Domain Context

This document explains what LogMind is, the problem it solves, the core domain concepts, and how data flows through the system. It contains no visual design, colors, or styling rules.

## 1. Product Mission

In microservice architectures, when a single component fails (for example, a database timeout), every upstream service that calls it also fails with timeouts and 5xx errors. A single failure produces thousands of error logs across multiple services within seconds.

Traditional log dashboards display a wall of disconnected logs. An engineer has to manually search, guess where the problem started, and trace requests across services.

LogMind solves this problem by automating the investigation workflow:
1. It ingests and normalizes logs from all services.
2. It detects error rate surges across sliding time windows.
3. It reconstructs distributed traces and uses service dependency topology to separate the initial root trigger from downstream cascading errors.
4. It correlates these related failures into a single stateful Incident.
5. It runs an autonomous AI agent that queries logs, traces, service topology, and runbooks to produce a root cause diagnosis backed by concrete evidence citations.

LogMind is an incident investigation console, not a generic conversational chatbot.

## 2. Core Domain Concepts

### 2.1 Multi-Tenancy
Every request in LogMind is scoped to a tenant identifier passed via the `X-Tenant-ID` header. Data is strictly isolated per tenant:
- Logs are stored in separate Elasticsearch indexes (`logmind-logs-<tenant>`).
- Runbooks are stored in separate indexes (`logmind-runbooks-<tenant>`).
- Database records (incidents, topologies, reports) are filtered by `tenant_id`.

### 2.2 Logs
A log record contains structured metadata:
- `timestamp`: ISO-8601 UTC timestamp.
- `level`: Log level (DEBUG, INFO, WARN, ERROR, FATAL).
- `message`: Text description of the event.
- `context`: Service name, tenant ID, and environment (production, staging).
- `trace`: Distributed tracing context, including `trace_id`, `span_id`, and `parent_span_id`.
- `http`: Optional HTTP metadata including method, path, and status code.
- `error`: Structured error information including error type, raw message, and extracted error signature.

### 2.3 Service Topology
The directed dependency graph connecting services in a system.
- Dependencies represent callers and targets: for example, `api-gateway -> order-service -> payment-service`.
- Upstream service: The caller (for example, `order-service` is upstream of `payment-service`).
- Downstream service: The dependency being called (for example, `payment-service` is downstream of `order-service`).
- Purpose: When `payment-service` fails, the correlation engine uses topology to recognize that subsequent errors in `order-service` and `api-gateway` are cascading symptoms, not separate incidents.

### 2.4 Incidents
An incident represents an active or historical failure event.
- `incident_id`: Unique UUID.
- `title`: Summary of the outage (for example, "Outage in payment-service: Stripe upstream timed out after 8000ms").
- `trigger_service`: The specific service where the failure originated.
- `trigger_signature`: The normalized signature of the first error.
- `affected_services`: All services that experienced errors as part of this failure chain.
- `severity`: Priority classification (LOW, MEDIUM, HIGH, CRITICAL).
- `status`: Lifecycle phase (DETECTED, INVESTIGATING, MITIGATED, RESOLVED).
- `events`: Ordered list of timeline events.

### 2.5 Initial Error vs Cascading Error
Within an incident's event timeline, events are categorized into distinct types:
- `INITIAL_ERROR`: The earliest abnormal event in the distributed trace. This is the root cause trigger.
- `CASCADING_ERROR`: Subsequent errors in upstream caller services caused directly by the initial error.
- `TIMEOUT`: Network or client timeouts waiting on downstream dependencies.
- `GATEWAY_5XX`: Boundary HTTP 500/502/504 errors surfaced to external clients.

### 2.6 AI Investigation and Evidence
When an incident is investigated, an AI agent executes an autonomous loop with access to read-only tools:
- `search_logs`: Searches Elasticsearch for relevant error patterns.
- `get_trace`: Retrieves the complete chronological span timeline for a trace ID.
- `search_runbooks`: Semantic search over troubleshooting documents using vector embeddings.
- `get_service_dependencies`: Queries the service topology graph for upstream and downstream services.
- `get_related_incidents`: Finds historical resolved incidents sharing the same error signature.

The output of an investigation is an Investigation Report:
- `summary`: Concise summary of what occurred.
- `suspected_root_cause`: Detailed technical explanation of the failure.
- `confidence_score`: Confidence rating from 0.0 to 1.0.
- `evidence`: List of concrete evidence citations. Every citation has an `evidence_type` (LOG, TRACE, RUNBOOK, HISTORICAL_INCIDENT), a `reference_id` (the exact log ID, trace ID, or runbook ID), and an excerpt.
- `recommended_actions`: Concrete steps the engineer should take to mitigate or fix the issue.
- `steps`: Audit log of every tool call executed by the agent, including tool name, arguments, output, and execution latency.
- `is_fallback`: Boolean indicating whether the report was generated by the live LLM or synthesized by the deterministic fallback engine during an LLM timeout.

### 2.7 Dead Letter Queue (DLQ)
When logs fail validation or indexing (for example, malformed JSON or unparseable schema), they are diverted to a Dead Letter Queue rather than discarded.
- Engineers can inspect the raw payload, failure stage, and error reason.
- Once the schema or issue is corrected, payloads can be replayed back into the ingestion queue.

### 2.8 Synthetic Simulator
A built-in simulator service used for testing and demonstrations:
- Can inject realistic failure scenarios: `PAYMENT_TIMEOUT`, `DB_POOL_EXHAUSTION`, `AUTH_DEPENDENCY_FAILURE`, `RETRY_STORM`.
- Can run steady-state background traffic at a configurable rate per second.
- Provides ground truth metadata to verify that detection and AI diagnosis match the simulated failure.

## 3. End-to-End User Workflows

### Workflow A: Incident Triage
1. The user selects an active tenant.
2. The user views the list of incidents, sorted by severity and recency.
3. The user selects an incident to review the details:
   - Root trigger service versus cascading services.
   - Chronological event timeline showing the exact propagation path across services.
4. The user starts an AI investigation if one has not yet run.
5. The user reviews the diagnosis, clicks on evidence citations to verify the underlying logs and traces, and follows the recommended actions.
6. The user updates the incident status from DETECTED to INVESTIGATING, MITIGATED, or RESOLVED.

### Workflow B: Exploratory Log and Trace Search
1. The user inputs a keyword, error signature, or semantic search query.
2. The user filters by service, log level, and time range.
3. The user inspects matching logs.
4. Clicking a log's trace ID retrieves all spans across all services belonging to that distributed transaction.

### Workflow C: Topology Management
1. The user inspects the current service dependency map.
2. The user registers new inter-service dependencies so the correlation engine can accurately track cascading paths.

### Workflow D: DLQ Inspection and Replay
1. The user checks if any logs failed ingestion.
2. The user inspects the raw payload and error message.
3. The user triggers a replay to process the logs again.

## 4. Backend API Contract Summary

All requests require authentication headers:
- `X-API-Key`: API key (default: `lmd_dev_key`).
- `X-Tenant-ID`: Tenant identifier (for example: `tenant-default`).

All responses follow a standard envelope:
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

### Key Endpoints

#### Ingestion and Search
- `POST /api/v1/logs/ingest`: Accepts an array of log payloads (HTTP 202).
- `POST /api/v1/logs/search`: Search logs with query, service, level, and time range filters.
- `GET /api/v1/dlq`: Retrieve failed log payloads.
- `POST /api/v1/dlq/replay`: Replay failed payloads.

#### Incidents and Topology
- `GET /api/v1/incidents`: List incidents (optional status filter).
- `GET /api/v1/incidents/{incident_id}`: Get complete incident record with timeline events.
- `POST /api/v1/incidents/evaluate`: Trigger an on-demand evaluation cycle over a time window.
- `PATCH /api/v1/incidents/{incident_id}/status`: Update incident status.
- `GET /api/v1/topology`: Retrieve service dependency graph.
- `POST /api/v1/topology/dependencies`: Register a service dependency.

#### AI Investigation
- `POST /api/v1/investigations/{incident_id}/start`: Start autonomous AI investigation.
- `GET /api/v1/investigations/{incident_id}`: Retrieve existing investigation report.
- `GET /api/v1/investigations/{incident_id}/steps`: Inspect autonomous tool loop audit steps.
- `POST /api/v1/runbooks`: Ingest a troubleshooting runbook into the vector database.

#### Simulator
- `GET /api/v1/simulator/status`: Check current simulation state.
- `POST /api/v1/simulator/start`: Start steady-state traffic simulation.
- `POST /api/v1/simulator/stop`: Stop steady-state simulation.
- `POST /api/v1/simulator/scenarios/trigger`: Inject a synthetic failure scenario.
