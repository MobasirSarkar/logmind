# LogMind — System Context & Design

## 1. Product Overview

LogMind is an engineering incident investigation platform for distributed applications.

Its purpose is to help developers move from:

> "There are thousands of logs. What went wrong?"

to:

> "The failure originated in `payment-service`, the first abnormal event was a connection-pool exhaustion, these logs and traces support the diagnosis, and these are the next actions to investigate."

LogMind is **not** intended to be a generic chatbot over logs.

The system combines:

- Structured log ingestion
- Full-text and filtered log search
- Semantic/vector search
- Trace and request correlation
- Incident detection and grouping
- Historical incident retrieval
- Runbook and service-document retrieval
- LLM-based investigation
- Controlled LLM tool calling
- Evidence-backed root-cause analysis
- Investigation history and auditability

The core design principle is:

> **Deterministic systems collect and correlate evidence; the LLM interprets that evidence.**

The LLM should not be responsible for discovering everything from raw logs by itself.

---

# 2. Problem Statement

Modern applications are composed of multiple services.

A single user request can pass through:

```text
API Gateway
    ↓
Auth Service
    ↓
Order Service
    ↓
Payment Service
    ↓
Notification Service
```

When something fails, each service can generate many log records.

A single incident may produce:

- application errors
- database errors
- timeout errors
- retry messages
- HTTP 5xx responses
- downstream failures
- cascading errors

Traditional log search can find matching strings, but it does not automatically answer:

1. Where did the failure start?
2. Which service was the likely source?
3. Which downstream errors were consequences?
4. Which traces were affected?
5. Has this happened before?
6. What operational documentation is relevant?
7. What should an engineer investigate next?

LogMind addresses this investigation workflow.

---

# 3. Goals

## Primary Goals

### 3.1 Centralized Log Ingestion

Accept logs from multiple applications and services through:

- REST ingestion API
- JSON log payloads
- File upload
- Optional collector integration

### 3.2 Structured Log Normalization

Convert different log formats into a common internal representation.

### 3.3 Fast Log Search

Support:

- keyword search
- service filtering
- environment filtering
- log-level filtering
- time-range filtering
- trace/request filtering
- metadata filtering

### 3.4 Semantic Search

Allow users to search conceptually.

Example:

> "database connection problems"

should retrieve logs describing:

- connection pool exhaustion
- connection refused
- database timeout
- PostgreSQL unavailable

even when the exact phrase is not present.

### 3.5 Incident Detection

Identify abnormal patterns such as:

- error-rate spikes
- repeated failures
- correlated failures across services
- repeated stack traces
- unusual latency/error patterns

### 3.6 Incident Correlation

Group related log records using:

- trace ID
- request ID
- service
- time window
- error signature
- dependency relationship

### 3.7 AI Investigation

Use an LLM to interpret structured evidence and produce:

- incident summary
- suspected root cause
- affected services
- supporting evidence
- confidence level
- recommended investigation steps

### 3.8 Tool Calling

Give the LLM controlled read-only tools such as:

- search logs
- retrieve a trace
- inspect service health
- retrieve related incidents
- inspect service dependencies
- retrieve runbooks
- inspect deployment history

### 3.9 Evidence-Based Output

Every important diagnosis should reference the evidence used to reach it.

---

# 4. Non-Goals

LogMind is not initially intended to:

- replace a full observability platform
- replace Elasticsearch
- automatically modify production infrastructure
- automatically restart production services
- execute destructive commands
- autonomously deploy fixes
- guarantee root-cause correctness
- act as a generic AI coding assistant

The initial system is an **investigation and decision-support platform**.

---

# 5. Core User Flow

```text
Developer
   ↓
Opens LogMind
   ↓
Selects environment/service/time range
   ↓
Searches logs or opens an incident
   ↓
Incident Engine groups correlated failures
   ↓
System builds investigation context
   ↓
Retriever searches:
   - logs
   - historical incidents
   - runbooks
   - service documentation
   ↓
LLM Investigator receives structured evidence
   ↓
LLM calls read-only investigation tools when needed
   ↓
Investigation result generated
   ↓
Developer reviews:
   - suspected root cause
   - evidence
   - timeline
   - affected services
   - recommendations
```

---

# 6. High-Level Architecture

```text
                           ┌──────────────────────┐
                           │      React UI        │
                           │  Incident Console    │
                           └──────────┬───────────┘
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │      FastAPI         │
                           │      API Layer       │
                           └──────────┬───────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
             ▼                        ▼                        ▼
    ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
    │ Log Ingestion   │     │ Incident Engine  │     │ AI Investigation │
    │ Service         │     │                  │     │ Service          │
    └────────┬────────┘     └─────────┬────────┘     └─────────┬────────┘
             │                        │                        │
             ▼                        ▼                        ▼
    ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
    │ Elasticsearch   │     │   PostgreSQL     │     │ RAG / Retriever  │
    │ Logs + Vectors  │     │ Incidents/Config │     │                  │
    └────────┬────────┘     └──────────────────┘     └─────────┬────────┘
             │                                                  │
             └──────────────────────┬───────────────────────────┘
                                    ▼
                           ┌──────────────────────┐
                           │     LLM Provider     │
                           │ Tool Calling + RCA   │
                           └──────────────────────┘
```

---

# 7. Major Components

## 7.1 Frontend

Recommended:

- React
- TypeScript
- Tailwind CSS

Responsibilities:

- authentication
- dashboard
- log explorer
- incident list
- incident detail
- investigation timeline
- service view
- trace view
- runbook/document management
- AI investigation interface

The UI should prioritize an **incident investigation console**, not a chatbot interface.

---

# 8. API Layer

Recommended:

- Python
- FastAPI
- Pydantic

Responsibilities:

- authentication and authorization
- tenant management
- log ingestion
- log search
- incident APIs
- investigation APIs
- service metadata
- runbooks
- documents
- AI orchestration

Example endpoints:

```text
POST   /api/v1/logs
POST   /api/v1/logs/upload

GET    /api/v1/logs
GET    /api/v1/logs/{id}

GET    /api/v1/traces/{trace_id}

GET    /api/v1/incidents
GET    /api/v1/incidents/{id}
POST   /api/v1/incidents/{id}/investigate

GET    /api/v1/services
GET    /api/v1/services/{id}

POST   /api/v1/runbooks
GET    /api/v1/runbooks

POST   /api/v1/documents
GET    /api/v1/investigations/{id}
```

---

# 9. Log Ingestion Architecture

## Input

A normalized log record should look like:

```json
{
  "timestamp": "2026-09-04T10:31:05.421Z",
  "level": "ERROR",
  "service": "payment-service",
  "environment": "production",
  "message": "connection timeout to payment provider",
  "trace_id": "abc123",
  "span_id": "xyz789",
  "request_id": "req-123",
  "host": "payment-01",
  "container": "payment-service-7d8f",
  "metadata": {
    "provider": "stripe",
    "timeout_ms": 3000
  }
}
```

## Normalization

The ingestion layer should normalize incoming logs into:

```text
LogRecord

id
timestamp
level
service
environment
message
trace_id
span_id
request_id
host
container
exception_type
stack_trace
metadata
embedding
```

Use consistent telemetry fields and preserve the original payload where useful.

---

# 10. Elasticsearch Design

Elasticsearch is the primary log search engine.

## Index

Example:

```text
logmind-logs-2026.09.04
```

For larger deployments, use time-based indices or data streams.

## Important Fields

```text
timestamp
service
environment
level
message
trace_id
span_id
request_id
host
container
exception_type
stack_trace
metadata
embedding
```

## Search Types

### Exact/filter search

```text
service = payment-service
level = ERROR
environment = production
timestamp >= last 30 minutes
```

### Full-text search

```text
"connection timeout"
```

### Semantic search

User:

```text
Why are payments failing?
```

The query is embedded and matched against log embeddings.

### Hybrid search

Combine:

```text
keyword relevance
+
vector similarity
+
metadata filters
```

This should be preferred over relying exclusively on vector search.

---

# 11. Embedding Pipeline

Logs should not all be blindly embedded individually.

The system should first normalize and optionally enrich the log.

Example:

```text
Raw Log
   ↓
Normalization
   ↓
Template / Error Signature
   ↓
Context Construction
   ↓
Embedding
   ↓
Elasticsearch Vector Field
```

For repetitive logs, consider grouping or templating them to reduce redundant embeddings.

Example:

```text
Raw:

Payment timeout for customer 123
Payment timeout for customer 456
Payment timeout for customer 789

Template:

Payment timeout for customer <ID>
```

The original logs remain searchable while the semantic representation can focus on the reusable failure pattern.

---

# 12. PostgreSQL Data Model

PostgreSQL stores application state and relational data.

## organizations

```text
id
name
created_at
```

## users

```text
id
organization_id
email
role
created_at
```

## services

```text
id
organization_id
name
environment
repository
team
created_at
```

## service_dependencies

```text
id
source_service_id
target_service_id
dependency_type
created_at
```

Example:

```text
checkout → payment
payment  → postgres
payment  → stripe
```

## incidents

```text
id
organization_id
title
severity
status
started_at
resolved_at
root_cause
confidence
created_at
```

## incident_events

```text
id
incident_id
event_type
service
timestamp
reference_id
description
```

## investigations

```text
id
incident_id
status
summary
root_cause
confidence
started_at
completed_at
```

## investigation_steps

```text
id
investigation_id
step_number
tool_name
input
output
created_at
```

This allows LogMind to preserve an auditable investigation trail.

## runbooks

```text
id
organization_id
service_id
title
content
version
created_at
updated_at
```

---

# 13. Incident Detection Engine

The Incident Engine is deterministic.

The initial version should use rules and statistical thresholds instead of an LLM.

## Detection signals

### Error-rate spike

```text
current error rate > baseline × threshold
```

### Repeated error signature

```text
same exception/error template
+
high frequency
+
short time window
```

### Multi-service correlation

```text
service A starts failing
↓
service B starts returning errors
↓
service C returns 500
```

### Trace correlation

Logs sharing the same:

```text
trace_id
request_id
```

can be reconstructed into a request timeline.

---

# 14. Incident Correlation

Example:

```text
10:31:02.412  auth-service      INFO   authentication successful
10:31:03.001  payment-service   INFO   payment started
10:31:05.421  payment-service   ERROR  provider timeout
10:31:05.439  order-service     ERROR  payment failed
10:31:05.442  gateway            ERROR  HTTP 500
```

The system should identify:

```text
First abnormal event:
payment-service provider timeout

Downstream consequences:
order-service payment failure
gateway HTTP 500
```

This distinction is critical.

The final error is not necessarily the root cause.

---

# 15. Error Signatures

Create normalized error signatures.

Example:

```text
Exception:
TimeoutError

Service:
payment-service

Message Template:
connection timeout to <provider>

Signature:
payment-service:TimeoutError:provider-timeout
```

This enables:

- aggregation
- frequency analysis
- historical comparison
- duplicate incident suppression

---

# 16. RAG Architecture

The RAG system has four major knowledge sources:

```text
                 ┌───────────────┐
                 │ Application   │
                 │ Logs          │
                 └───────┬───────┘
                         │
                 ┌───────▼───────┐
                 │ Vector Search │
                 └───────┬───────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
Historical Incidents   Runbooks       Service Docs
```

The retrieval process:

```text
User question / Incident
        ↓
Query construction
        ↓
Metadata filters
        ↓
Keyword retrieval
        +
Vector retrieval
        ↓
Rank / merge results
        ↓
Context window
        ↓
LLM
```

---

# 17. LLM Investigation Engine

The LLM should receive a structured investigation context.

Example:

```json
{
  "incident": {
    "id": "INC-184",
    "title": "Checkout failures",
    "severity": "high"
  },
  "services": [
    "gateway",
    "checkout-service",
    "payment-service"
  ],
  "timeline": [],
  "error_summary": {},
  "relevant_logs": [],
  "historical_incidents": [],
  "runbooks": [],
  "service_dependencies": []
}
```

The LLM then analyzes this evidence.

It should return structured output:

```json
{
  "summary": "Checkout failures originated in payment-service.",
  "root_cause": "Payment provider connection timeouts caused payment requests to fail.",
  "confidence": 0.91,
  "affected_services": [
    "payment-service",
    "checkout-service",
    "gateway"
  ],
  "evidence": [
    {
      "type": "log",
      "id": "log-123"
    },
    {
      "type": "trace",
      "id": "trace-abc123"
    }
  ],
  "recommended_actions": [
    "Check payment provider latency.",
    "Inspect connection pool utilization.",
    "Review timeout configuration."
  ]
}
```

---

# 18. LLM Tool Calling

The LLM should not receive unrestricted access to infrastructure.

Tools should be explicit and read-only.

## search_logs

```text
search_logs(
    query,
    service,
    environment,
    start_time,
    end_time,
    level
)
```

## get_trace

```text
get_trace(trace_id)
```

Returns all correlated logs/events.

## get_service_health

```text
get_service_health(service, start_time, end_time)
```

## get_related_incidents

```text
get_related_incidents(error_signature)
```

## get_service_dependencies

```text
get_service_dependencies(service)
```

## search_runbooks

```text
search_runbooks(query, service)
```

## get_deployment_history

```text
get_deployment_history(service, start_time, end_time)
```

The LLM can choose which tools are necessary.

---

# 19. Investigation Workflow

Example:

```text
User:
Why did checkout start failing around 10:30?

        ↓

LLM
        ↓
search_logs(
  service="checkout",
  time_range="10:20-10:40",
  level="ERROR"
)

        ↓

Finds payment failures

        ↓

get_trace(trace_id)

        ↓

Finds payment-service timeout

        ↓

get_service_health(payment-service)

        ↓

Finds connection-pool saturation

        ↓

get_related_incidents(payment-timeout)

        ↓

Finds previous similar incident

        ↓

search_runbooks(payment-service)

        ↓

Generate diagnosis
```

Every tool invocation should be persisted in `investigation_steps`.

---

# 20. Evidence Model

Every AI conclusion should be connected to evidence.

Example:

```text
Root Cause:
Payment connection pool exhaustion

Evidence:
├── log-81231
├── log-81242
├── trace-abc123
├── incident-1042
└── runbook-payment-01
```

The UI should allow the engineer to click each evidence item and inspect the underlying record.

This reduces hallucination risk and makes the system useful during real investigations.

---

# 21. Incident Timeline

The incident page should render a timeline:

```text
10:31:02
Auth successful
        │
10:31:03
Payment request started
        │
10:31:05
Payment provider timeout
        │
10:31:05
Order payment failed
        │
10:31:05
Gateway returned HTTP 500
```

The timeline is generated primarily from deterministic telemetry.

The LLM can summarize it but should not invent timeline events.

---

# 22. Multi-Tenancy

LogMind should be designed as a multi-tenant SaaS application.

Every organization-owned record should include:

```text
organization_id
```

Tenant isolation must apply to:

- logs
- incidents
- users
- services
- runbooks
- documents
- investigations

Search queries must always include tenant boundaries.

Example:

```text
organization_id = current_user.organization_id
```

This filter must be enforced server-side rather than relying on the frontend.

---

# 23. Authentication and Authorization

Initial roles:

```text
Admin
Engineer
Viewer
```

Permissions:

### Admin

- manage users
- manage services
- manage runbooks
- configure integrations
- view incidents

### Engineer

- search logs
- investigate incidents
- view services
- view runbooks

### Viewer

- read-only incident access
- read-only logs

---

# 24. Asynchronous Processing

Not every operation should happen inside the HTTP request.

Potential background jobs:

```text
log ingestion enrichment
embedding generation
large file parsing
incident detection
incident aggregation
RAG indexing
document processing
```

Initial implementation can use a lightweight worker architecture.

A queue such as RabbitMQ, Redis Streams, or another message broker can be introduced when workload requires it.

Do not introduce a broker merely for architectural decoration.

---

# 25. Caching

Redis can be used for:

- frequently accessed service metadata
- incident summaries
- rate limiting
- short-lived investigation state
- API response caching
- job coordination where appropriate

Do not cache raw logs aggressively because Elasticsearch is the source of truth for log search.

---

# 26. Reliability

Important failure scenarios:

## Elasticsearch unavailable

Log ingestion should not silently lose logs.

Possible strategy:

```text
Producer
   ↓
Durable queue
   ↓
Indexer
   ↓
Elasticsearch
```

If the first version does not use a queue, document the tradeoff.

## LLM unavailable

Normal log search and incident investigation should continue.

AI investigation becomes temporarily unavailable rather than taking down the core product.

## Embedding provider unavailable

Logs should still be indexed for normal search.

Semantic indexing can retry asynchronously.

## PostgreSQL unavailable

Application state operations fail gracefully.

---

# 27. Security

The system handles potentially sensitive operational data.

Requirements:

- tenant isolation
- authentication
- RBAC
- input validation
- API rate limiting
- secure secrets management
- encrypted connections
- audit logs
- no arbitrary shell execution by the LLM
- no unrestricted production access
- sanitized LLM context where necessary

LLM tools should be **read-only by default**.

---

# 28. Observability of LogMind

LogMind itself should produce telemetry.

Track:

```text
API latency
ingestion throughput
Elasticsearch query latency
embedding latency
LLM latency
LLM token usage
tool invocation count
investigation duration
incident detection latency
queue depth
failed jobs
```

Useful metrics:

```text
logs_ingested_total
logs_indexed_total
log_search_latency
embedding_latency
llm_request_latency
investigations_total
investigation_failures_total
tool_calls_total
```

---

# 29. Performance Targets

Initial engineering targets:

```text
Log ingestion:
10K+ logs/sec target for benchmark environment

Keyword search:
<100 ms average target for indexed/filter queries

Semantic retrieval:
<200 ms average target under benchmark workload

API:
<200 ms average for normal non-AI endpoints

Incident detection:
near-real-time processing

LLM investigation:
dependent on model/provider latency
```

These are **engineering targets**, not claimed production results.

Actual benchmark numbers should be measured before being included in the resume.

---

# 30. Load Testing

Create a synthetic distributed application that generates realistic logs.

Example services:

```text
gateway
auth
order
payment
notification
```

Generate:

- normal traffic
- database errors
- timeouts
- authentication failures
- payment provider failures
- retry storms
- cascading failures

Example workload:

```text
100K synthetic logs
500K synthetic logs
1M synthetic logs
```

Benchmark:

- ingestion throughput
- indexing throughput
- search latency
- semantic retrieval latency
- incident detection latency
- memory usage
- CPU usage

---

# 31. Synthetic Incident Scenarios

The project should include reproducible incidents.

## Scenario 1 — Payment Timeout

```text
Payment provider latency increases
        ↓
Payment service timeout
        ↓
Order service failure
        ↓
Gateway 500
```

Expected root cause:

```text
Payment provider timeout
```

## Scenario 2 — Database Connection Pool Exhaustion

```text
DB latency increases
        ↓
Connection pool fills
        ↓
API requests timeout
        ↓
Gateway 5xx spike
```

Expected root cause:

```text
Database connection pool exhaustion
```

## Scenario 3 — Authentication Dependency Failure

```text
Auth DB unavailable
        ↓
Authentication failures
        ↓
Order requests rejected
        ↓
Gateway errors
```

Expected root cause:

```text
Auth service dependency failure
```

## Scenario 4 — Retry Storm

```text
Downstream timeout
        ↓
Aggressive retries
        ↓
Request amplification
        ↓
Service saturation
        ↓
Cascading failures
```

Expected root cause:

```text
Retry amplification caused by downstream timeout
```

These scenarios are important because they provide a controlled way to validate the investigation engine.

---

# 32. Frontend Screens

## Dashboard

Show:

```text
Active Incidents
Error Rate
Services
Recent Investigations
Log Volume
```

## Log Explorer

Features:

- search
- filters
- time range
- service
- level
- trace ID
- expandable log details

## Incident List

Columns:

```text
ID
Severity
Service
Title
Status
Started
Updated
```

## Incident Detail

Sections:

```text
Summary
Root Cause
Confidence
Affected Services
Timeline
Evidence
Related Incidents
Recommended Actions
AI Investigation
```

## Service Detail

Show:

```text
service health
error rate
latency
recent incidents
dependencies
recent deployments
```

## Investigation View

Show:

```text
Question
Tool Calls
Retrieved Evidence
Reasoning Summary
Diagnosis
Confidence
Recommendations
```

Do not expose hidden chain-of-thought. Show concise investigation steps and evidence instead.

---

# 33. Repository Structure

Recommended structure:

```text
logmind/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── ingestion/
│   │   ├── search/
│   │   ├── incidents/
│   │   ├── ai/
│   │   ├── tools/
│   │   └── workers/
│   │
│   ├── tests/
│   ├── migrations/
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── features/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── types/
│   └── Dockerfile
│
├── simulator/
│   ├── services/
│   ├── scenarios/
│   └── generators/
│
├── infrastructure/
│   ├── docker/
│   └── scripts/
│
├── docs/
│
├── docker-compose.yml
├── README.md
└── context.md
```

---

# 34. Development Order

Build in this order.

## Stage 1 — Core Log Platform

```text
FastAPI
PostgreSQL
Elasticsearch
React
Docker
```

Implement:

- authentication
- log ingestion
- normalization
- indexing
- search
- filtering
- log viewer

## Stage 2 — Distributed Correlation

Implement:

- trace correlation
- request correlation
- error signatures
- service dependencies
- incident grouping
- timeline generation

## Stage 3 — RAG

Implement:

- embeddings
- vector indexing
- semantic retrieval
- hybrid search
- runbooks
- historical incidents

## Stage 4 — AI Investigation

Implement:

- LLM integration
- structured output
- tool calling
- investigation orchestration
- evidence references
- confidence scoring

## Stage 5 — Production Engineering

Implement:

- background workers
- retries
- rate limiting
- observability
- load testing
- CI/CD
- security hardening

---

# 35. Architectural Principles

## Principle 1 — Evidence Before AI

The LLM should interpret evidence, not replace the search engine.

## Principle 2 — Deterministic Correlation

Trace/request correlation should be implemented by the system.

Do not ask an LLM to infer relationships that already exist in structured telemetry.

## Principle 3 — Read-Only AI

The initial AI system should investigate, not modify infrastructure.

## Principle 4 — Explicit Evidence

AI conclusions should reference the logs, traces, incidents, or documentation supporting them.

## Principle 5 — Graceful AI Failure

The core log platform must remain useful when the LLM provider is unavailable.

## Principle 6 — Multi-Tenant by Design

Tenant boundaries must exist at the data and API layers from the beginning.

## Principle 7 — Measure Before Claiming

Performance metrics used in documentation or a resume must come from reproducible benchmarks.

---

# 36. Key Engineering Tradeoffs

## Elasticsearch vs PostgreSQL for logs

Use Elasticsearch for:

- large-scale log search
- full-text search
- filtering
- vector search

Use PostgreSQL for:

- users
- organizations
- services
- incidents
- relationships
- configuration

Do not use PostgreSQL as the primary high-volume log search engine for this project.

## Synchronous vs asynchronous ingestion

Synchronous ingestion is simpler.

Asynchronous ingestion provides:

- buffering
- backpressure
- retries
- better throughput

Start simple and introduce a durable queue when benchmark results justify it.

## LLM-first vs rules-first investigation

Rules-first is preferred.

Advantages:

- predictable
- cheaper
- faster
- easier to test
- easier to debug

The LLM should handle interpretation and investigation, not basic telemetry processing.

---

# 37. Definition of Done

LogMind is considered portfolio-ready when a user can:

1. Sign in.
2. Create/select an organization.
3. Register services.
4. Ingest logs.
5. Search logs.
6. Filter logs by service/time/level.
7. Correlate logs using trace IDs.
8. Detect or create an incident.
9. View an incident timeline.
10. Retrieve related historical incidents.
11. Search runbooks semantically.
12. Start an AI investigation.
13. Allow the LLM to call read-only investigation tools.
14. Receive a structured diagnosis.
15. Inspect evidence supporting the diagnosis.
16. View investigation history.
17. Run the complete system locally with Docker Compose.
18. Run a synthetic failure scenario and reproduce the diagnosis.
19. Run load tests and record measured performance.

---

# 38. Portfolio Positioning

The project should be presented as:

> **LogMind — LLM-Powered Log Intelligence & Incident Investigation Platform**

Short description:

> A developer platform that ingests and correlates distributed application logs, combines keyword and semantic retrieval with historical incidents and runbooks, and uses an LLM with controlled tool calling to perform evidence-backed incident investigation and root-cause analysis.

The strongest technical story is:

```text
Distributed logs
      ↓
Normalization
      ↓
Search + Correlation
      ↓
Incident Detection
      ↓
RAG Retrieval
      ↓
LLM Tool Calling
      ↓
Evidence-backed Investigation
```

The project should demonstrate that the engineer understands **both sides of the system**:

- building reliable backend/search infrastructure
- integrating AI into that infrastructure in a controlled and measurable way

The goal is not to make the LLM look impressive.

The goal is to make **the entire engineering system** impressive.
