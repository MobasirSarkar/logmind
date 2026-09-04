# LogMind — Service 1: Log Ingestion, Normalization & Hybrid Search Platform Design

**Date:** 2026-09-04  
**Author:** LogMind Team  
**Status:** Approved for Implementation  
**Scope:** Service 1 of LogMind Distributed Architecture  

---

## 1. Executive Summary

LogMind is an engineering incident investigation platform for distributed applications. This specification designs **Service 1: Log Ingestion, Normalization & Hybrid Search Platform**. 

Service 1 provides the foundational telemetry ingestion pipeline and hybrid search engine for the platform. It accepts high-throughput structured log batches from distributed external services over HTTPS, buffers them via a high-performance Redis queue, normalizes them into modular type-safe models, selectively extracts and embeds normalized error signatures using local ONNX embeddings (`fastembed`), indexes records into Dockerized Elasticsearch 8.x with `dense_vector` support, and provides a developer-facing Dead-Letter Queue (DLQ) and Hybrid Search query API.

The entire implementation adheres strictly to **Test-Driven Development (TDD)**: tests are written first to establish failing assertions before implementation code is written.

---

## 2. Architectural Topology & Components

```text
┌─────────────────────────┐
│ External App / Service  │
│ (HTTP JSON Log Batches) │
└────────────┬────────────┘
             │ POST /api/v1/logs/ingest
             ▼
┌─────────────────────────┐
│       FastAPI App       │◄─── GET /api/v1/logs/search (BM25)
│  (Ingestion & Search)   │◄─── POST /api/v1/logs/semantic-search (kNN)
│                         │◄─── GET/POST/DELETE /api/v1/dlq (Inspection & Replay)
└────────────┬────────────┘
             │ LPUSH
             ▼
┌─────────────────────────┐
│       Redis 7.x         │
│  (Queue: logmind:queue) │
└────────────┬────────────┘
             │ BRPOP / RPOPLPUSH (Batch)
             ▼
┌─────────────────────────┐
│  Log Processing Worker  │
│  - Schema Normalizer    │
│  - Signature Extractor  │
│  - FastEmbed ONNX (CPU) │
│  - Embedding LRU Cache  │
└────────────┬────────────┘
             │ async_bulk
             ▼
┌─────────────────────────┐
│   Elasticsearch 8.x     │
│ (BM25 + dense_vector)   │
│ logmind-logs-{tenant}-* │
└─────────────────────────┘
```

### Component Roles
1. **FastAPI Ingestion Gateway:** Validates API key and tenant ID, accepts JSON log batches, enqueues payloads onto Redis, and immediately returns `202 Accepted` with a `batch_id`. Exposes query and DLQ endpoints.
2. **Redis Queue Buffer:** Absorb traffic spikes during multi-service incidents without dropping data.
3. **Log Processing Worker:** Python async worker that drains Redis, performs validation and field normalization, extracts regex-sanitized error signatures, generates dense embeddings for error logs, caches vectors by signature hash, and performs bulk writes to Elasticsearch.
4. **Local FastEmbed ONNX Model:** `BAAI/bge-small-en-v1.5` generating 384-dimensional dense vectors running 100% on CPU. Incurs zero external API costs.
5. **Elasticsearch 8.x:** Stores normalized logs with BM25 inverted indices and HNSW dense vector indices for hybrid retrieval.
6. **Developer Dead-Letter Queue (DLQ):** Captures logs that repeatedly fail validation, embedding, or indexing after 3 retries with full stack traces and developer inspection/replay endpoints.

---

## 3. Domain Data Models & Type Safety

All data structures are implemented with Pydantic v2 with strict type validation and explicit enums.

```python
import uuid
import ipaddress
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

TMetadata = TypeVar("TMetadata", default=Dict[str, Any])
TPayload = TypeVar("TPayload", default=Dict[str, Any])

# --- Enums ---

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"

class HashType(str, Enum):
    SHA256 = "sha256"
    MD5 = "md5"

class ErrorStage(str, Enum):
    VALIDATION = "VALIDATION"
    SIGNATURE_EXTRACTION = "SIGNATURE_EXTRACTION"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"

# --- Composable Sub-Models ---

class ServiceContext(BaseModel):
    tenant_id: str
    service: str
    environment: str = "production"

class TraceContext(BaseModel):
    trace_id: str
    span_id: Optional[str] = None
    request_id: Optional[str] = None

class HttpContext(BaseModel):
    method: str
    path: str
    status_code: int

class ErrorInfo(BaseModel):
    error_type: str
    error_message: str
    error_signature: Optional[str] = None  # Sanitized regex template
    stack_trace: Optional[str] = None

class LogFingerprint(BaseModel):
    content_hash: str                      # SHA-256 for document deduplication
    signature_hash: Optional[str] = None   # Hash of normalized error template
    hash_type: HashType = HashType.SHA256
    embedding: Optional[List[float]] = None # 384-dim vector
    model_name: Optional[str] = "BAAI/bge-small-en-v1.5"

# --- Root Log Record ---

class LogRecord(BaseModel, Generic[TMetadata]):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime
    level: LogLevel
    message: str
    context: ServiceContext
    trace: Optional[TraceContext] = None
    http: Optional[HttpContext] = None
    error: Optional[ErrorInfo] = None
    fingerprint: Optional[LogFingerprint] = None
    metadata: TMetadata = Field(default_factory=dict)

# --- Ingestion Batch Models ---

class LogBatchRequest(BaseModel):
    logs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=500)

class LogBatchResponse(BaseModel):
    status: str = "queued"
    batch_id: str
    received_count: int
    tenant_id: str

# --- Developer DLQ Model ---

class DLQEntry(BaseModel, Generic[TPayload]):
    dlq_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    failed_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int
    error_stage: ErrorStage
    last_error: str
    raw_payload: TPayload

---

## 4. Ingestion & Worker Pipeline

### 4.1 Ingestion Flow
1. Client issues `POST /api/v1/logs/ingest` with `X-API-Key` and `X-Tenant-ID` headers.
2. Ingestion Gateway verifies authentication and checks queue capacity.
3. If Redis queue depth exceeds `50,000` items, the API responds with `429 Too Many Requests` (`Retry-After: 5`) to preserve stability.
4. Otherwise, payload is pushed to Redis list `logmind:queue:{tenant_id}` via `LPUSH`.
5. API returns `202 Accepted` with `batch_id` and item count within <5ms.

### 4.2 Worker Processing Loop
1. Worker polls Redis queues using `BRPOP` or `RPOPLPUSH` in batches (up to 500 records or 500ms timeout).
2. For each record:
   - **Validation:** Normalizes input dictionary into `LogRecord`. If validation fails after 3 retries, entry is pushed to `logmind:dlq:{tenant_id}` with `ErrorStage.VALIDATION`.
   - **Content Hash Computation:** Computes SHA-256 of `(tenant_id + service + timestamp + message + trace_id)` to establish an idempotent Elasticsearch document `_id`.
   - **Selective Embedding:**
     - If `level in (LogLevel.ERROR, LogLevel.FATAL)` or `record.error is not None`:
       - Extracts sanitized error template.
       - Computes `signature_hash = sha256(error_signature)`.
       - Checks LRU embedding cache: if hit, reuses vector; if miss, calls FastEmbed ONNX model, stores in cache, and populates `fingerprint.embedding`.
3. **Bulk Indexing:**
   - Bundles normalized records into Elasticsearch `async_bulk` index actions.
   - Target index: `logmind-logs-{tenant_id}-{YYYY.MM}`.
   - On Elasticsearch transient failure: exponential backoff (1s, 2s, 4s). If max retries (3) exceeded, failed records route to DLQ with `ErrorStage.INDEXING`.

---

## 5. Error Signature Normalization & Embedding Cache

### 5.1 Tokenizer & Parser-Based Sanitization (No Regex)
Dynamic values in error messages are normalized using strict standard-library parsers and token classifiers rather than brittle regular expressions:
1. **Tokenization:** Split error message into whitespace/delimiter tokens while preserving syntactic structure.
2. **Type Parsing Pipeline:** Each token is evaluated against standard parser guards in sequence:
   - `uuid.UUID(token)` $\to$ replace with `<UUID>`
   - `ipaddress.ip_address(token)` $\to$ replace with `<IP>`
   - `datetime.fromisoformat(token)` $\to$ replace with `<TIMESTAMP>`
   - Hex parsing (`token.startswith("0x")` and valid hex digits) $\to$ replace with `<HEX>`
   - Numeric integer validation (`token.isdigit()`) $\to$ replace with `<ID>`
3. **Template Reconstruction:** Reconstruct sanitized template string and compute SHA-256 hash as `signature_hash`.
### 5.2 Embedding Cache
* Vector computation takes ~15ms on CPU. In an incident where 5,000 identical database timeout errors occur, generating embeddings on every record wastes 75 seconds of CPU time.
* By caching embeddings against `signature_hash`, the embedding is computed once and reused 4,999 times, achieving near-zero latency overhead.

---

## 6. Elasticsearch Index Mapping & Hybrid Search

### 6.1 Index Template & Mapping
Index pattern: `logmind-logs-*`
```json
{
  "mappings": {
    "properties": {
      "id": { "type": "keyword" },
      "timestamp": { "type": "date" },
      "level": { "type": "keyword" },
      "message": { "type": "text", "analyzer": "standard" },
      "context": {
        "properties": {
          "tenant_id": { "type": "keyword" },
          "service": { "type": "keyword" },
          "environment": { "type": "keyword" }
        }
      },
      "trace": {
        "properties": {
          "trace_id": { "type": "keyword" },
          "span_id": { "type": "keyword" },
          "request_id": { "type": "keyword" }
        }
      },
      "http": {
        "properties": {
          "method": { "type": "keyword" },
          "path": { "type": "keyword" },
          "status_code": { "type": "integer" }
        }
      },
      "error": {
        "properties": {
          "error_type": { "type": "keyword" },
          "error_message": { "type": "text" },
          "error_signature": { "type": "text" },
          "stack_trace": { "type": "text" }
        }
      },
      "fingerprint": {
        "properties": {
          "content_hash": { "type": "keyword" },
          "signature_hash": { "type": "keyword" },
          "hash_type": { "type": "keyword" },
          "model_name": { "type": "keyword" },
          "embedding": {
            "type": "dense_vector",
            "dims": 384,
            "index": true,
            "similarity": "cosine"
          }
        }
      },
      "metadata": { "type": "object" }
    }
  }
}
```

### 6.2 Hybrid Search Mechanics
Query endpoint: `POST /api/v1/logs/search`
Accepts:
- `query`: text string
- `service`, `level`, `trace_id`, `start_time`, `end_time`: filters
- `search_mode`: `exact` | `semantic` | `hybrid`

In `hybrid` mode, Elasticsearch executes:
1. **BM25 Search:** Multi-match across `message`, `error.error_message`, and `error.error_type`.
2. **Dense Vector kNN:** Vector similarity of FastEmbed query vector against `fingerprint.embedding` pre-filtered by tenant, service, and time range.
3. **Reciprocal Rank Fusion (RRF):** Merges both ranked lists with $k=60$ penalty constant to ensure top-ranked relevance.

---

## 7. Developer Dead-Letter Queue (DLQ)

### 7.1 DLQ Storage
Failed records are stored in Redis Hash / List (`logmind:dlq:{tenant_id}`) with structured metadata:
- `dlq_id`: Unique identifier
- `tenant_id`: Owning tenant
- `failed_at`: Timestamp of terminal failure
- `retry_count`: Number of failed attempts (always $\ge 3$)
- `error_stage`: `ErrorStage` Enum (`VALIDATION`, `SIGNATURE_EXTRACTION`, `EMBEDDING`, `INDEXING`)
- `last_error`: Formatted error message and exception trace
- `raw_payload`: Unmodified original input JSON

### 7.2 Developer DLQ Endpoints
* `GET /api/v1/dlq`: Paginated list of DLQ entries for the authenticated tenant with optional filtering by `error_stage`.
* `GET /api/v1/dlq/{dlq_id}`: Retrieve detailed entry including full raw JSON payload and stack trace.
* `POST /api/v1/dlq/{dlq_id}/replay`: Re-queues the record into `logmind:queue:{tenant_id}` for re-processing.
* `DELETE /api/v1/dlq/{dlq_id}`: Permanently discards the DLQ entry.

---

## 8. Test-Driven Development (TDD) Strategy

All features are implemented following the **Red $\to$ Green $\to$ Refactor** cycle.

### 8.1 Test Suites Structure
```text
tests/
├── unit/
│   ├── test_schemas.py            # Pydantic validation, enums, optional fields
│   ├── test_error_signatures.py   # Regex sanitization and hashing rules
│   ├── test_embeddings.py         # FastEmbed ONNX output shape & signature cache
│   └── test_dlq_models.py         # DLQEntry model and ErrorStage validation
├── integration/
│   ├── test_ingest_api.py         # POST /ingest, headers, 202 status, 429 backpressure
│   ├── test_worker_pipeline.py    # Redis BRPOP -> normalizer -> ES bulk indexing
│   ├── test_hybrid_search.py      # BM25, kNN vector, and RRF search execution
│   └── test_dlq_api.py            # DLQ inspection, replay, and delete endpoints
```

### 8.2 TDD Implementation Sequence
1. **Phase 1: Schemas & Normalization (Unit TDD)**
   - Test: Write failing tests for `LogLevel`, `ErrorStage`, `HashType`, `LogRecord`, `LogFingerprint`.
   - Code: Implement models in `app/models/log.py`.
   - Test: Write failing tests for error signature regex and hashing.
   - Code: Implement `app/services/normalizer.py`.
2. **Phase 2: Local Embeddings & Cache (Unit TDD)**
   - Test: Write failing tests asserting 384-dimensional vector output from FastEmbed and cache hit behavior.
   - Code: Implement `app/services/embeddings.py`.
3. **Phase 3: Ingestion API & Redis Queue (Integration TDD)**
   - Test: Write failing test for `POST /api/v1/logs/ingest` with mock Redis verifying LPUSH and 202 response.
   - Code: Implement FastAPI route `app/api/ingest.py`.
4. **Phase 4: Indexing Worker & Elasticsearch (Integration TDD)**
   - Test: Write failing test asserting batch consumption from Redis and bulk indexing into Elasticsearch.
   - Code: Implement `app/workers/indexer.py`.
5. **Phase 5: Hybrid Search & DLQ Endpoints (Integration TDD)**
   - Test: Write failing test for BM25 + kNN hybrid search and DLQ replay endpoint.
   - Code: Implement `app/api/search.py` and `app/api/dlq.py`.

---

## 9. Definition of Done for Service 1

1. All unit and integration test suites pass with 100% green status via `pytest`.
2. Docker Compose starts Redis 7 and Elasticsearch 8.x locally and passes health checks.
3. Ingestion API accepts a batch of 500 logs and returns `202 Accepted` in under 10ms.
4. Indexing worker processes logs, caches embeddings, and indexes them into Elasticsearch.
5. Hybrid search queries successfully retrieve exact error codes and semantic concept matches.
6. Deliberately corrupted logs route to DLQ after 3 retries and can be inspected and replayed via `/api/v1/dlq`.
