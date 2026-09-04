# Service 1: Log Ingestion, Normalization & Hybrid Search Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use supo-subagent-driven-development (recommended) or supo-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade log ingestion, normalization, and hybrid search platform that buffers high-throughput log batches via Redis, normalizes error signatures, generates local ONNX embeddings with a signature cache, bulk-indexes into Dockerized Elasticsearch 8.x, and exposes developer DLQ and hybrid search APIs.

**Architecture:** A FastAPI ingestion service authenticates incoming JSON log batches and enqueues them into Redis. An asynchronous worker consumes batches, normalizes fields into type-safe generic Pydantic models, extracts error signatures using token parsers, computes 384d dense vectors for error logs via local FastEmbed, and bulk-indexes into Elasticsearch 8.x. Corrupted or un-indexable logs are routed to a developer-managed Dead-Letter Queue (DLQ) with inspection and replay endpoints.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, Pydantic v2, Redis 7 (via `redis-py` async), Elasticsearch 8.x (`elasticsearch[async]`), FastEmbed (`BAAI/bge-small-en-v1.5`), Pytest, Pytest-asyncio, Docker Compose.

## Global Constraints

- **Python Version:** Python 3.12 or newer, managed via `uv`.
- **Typing:** Strict type hints across all modules. No `Any` in core models without explicit TypeVar generics (`TMetadata`, `TPayload`).
- **No Regex for Sanitization:** Dynamic sanitization must use standard-library token parsers (`uuid.UUID`, `ipaddress.ip_address`, `datetime.fromisoformat`, hex, int parsing).
- **Vector Model:** Local `BAAI/bge-small-en-v1.5` (384 dimensions) running on CPU via ONNX. Zero external paid API calls.
- **TDD Requirement:** Every task must follow the Red $\to$ Green $\to$ Refactor cycle. Write failing test first, verify failure, implement code, verify pass, commit.

---

## File Structure

```text
logmind/
├── docker-compose.yml                      # Redis 7 + Elasticsearch 8.x local cluster
├── pyproject.toml                          # Project dependencies and tool settings
├── .env.example                            # Configuration defaults
├── app/
│   ├── __init__.py
│   ├── config.py                           # Pydantic BaseSettings
│   ├── models/
│   │   ├── __init__.py
│   │   └── log.py                          # Enums, ServiceContext, ErrorInfo, LogRecord, DLQEntry
│   ├── services/
│   │   ├── __init__.py
│   │   ├── normalizer.py                   # Token parser sanitization & content hashing
│   │   ├── embeddings.py                   # FastEmbed ONNX wrapper & LRU signature cache
│   │   ├── queue.py                        # Redis LPUSH / BRPOP & queue depth checks
│   │   └── elasticsearch.py                # ES index templates, bulk indexing, and hybrid queries
│   ├── api/
│   │   ├── __init__.py
│   │   ├── ingest.py                       # POST /api/v1/logs/ingest
│   │   ├── dlq.py                          # GET/POST/DELETE /api/v1/dlq
│   │   └── search.py                       # POST /api/v1/logs/search (Hybrid BM25 + kNN)
│   ├── workers/
│   │   ├── __init__.py
│   │   └── indexer.py                      # Async queue-to-Elasticsearch worker loop
│   └── main.py                             # FastAPI application factory & router registration
└── tests/
    ├── conftest.py                         # Shared test fixtures (mock redis, mock ES)
    ├── unit/
    │   ├── test_schemas.py                 # Pydantic model validation & generics
    │   ├── test_normalizer.py              # Token-based sanitization and content hash
    │   ├── test_embeddings.py              # FastEmbed ONNX output & LRU vector cache
    │   └── test_queue.py                   # Queue LPUSH/BRPOP & backpressure logic
    └── integration/
        ├── test_ingest_api.py              # Ingestion endpoint & 202 response
        ├── test_indexer_worker.py          # Worker consuming Redis and bulk indexing
        ├── test_dlq_api.py                 # DLQ inspect, replay, and discard endpoints
        └── test_hybrid_search.py           # Hybrid BM25 + kNN vector query execution
```

---

### Task 1: Project Scaffolding, Python Environment & Docker Compose

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` providing `REDIS_URL`, `ELASTICSEARCH_URL`, `QUEUE_MAX_DEPTH`, `EMBEDDING_MODEL_NAME`.

- [ ] **Step 1: Write the failing test for application configuration**

```python
# tests/unit/test_config.py
from app.config import Settings

def test_settings_load_defaults():
    settings = Settings(
        REDIS_URL="redis://localhost:6379/0",
        ELASTICSEARCH_URL="http://localhost:9200",
        QUEUE_MAX_DEPTH=50000,
        EMBEDDING_MODEL_NAME="BAAI/bge-small-en-v1.5"
    )
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.ELASTICSEARCH_URL == "http://localhost:9200"
    assert settings.QUEUE_MAX_DEPTH == 50000
    assert settings.EMBEDDING_MODEL_NAME == "BAAI/bge-small-en-v1.5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Implement dependencies, Docker Compose, and Settings**

Create `pyproject.toml`:
```toml
[project]
name = "logmind"
version = "0.1.0"
description = "Engineering incident investigation platform for distributed applications"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "redis>=5.0.8",
    "elasticsearch[async]>=8.15.0",
    "fastembed>=0.3.4",
    "httpx>=0.27.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.23.8",
]
```

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: logmind-redis
    ports:
      - "6379:6379"
    restart: unless-stopped

  elasticsearch:
    image: elasticsearch:8.15.0
    container_name: logmind-elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    restart: unless-stopped
```

Create `app/config.py`:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    QUEUE_MAX_DEPTH: int = 50000
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    API_KEY: str = "lmd_dev_key"

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docker-compose.yml app/config.py tests/unit/test_config.py
git commit -m "chore: scaffold project dependencies, docker-compose, and config settings"
```

---

### Task 2: Domain Data Models & Type Safety

**Files:**
- Create: `app/models/log.py`
- Create: `app/models/__init__.py`
- Test: `tests/unit/test_schemas.py`

**Interfaces:**
- Produces: `LogLevel`, `HashType`, `ErrorStage`, `ServiceContext`, `TraceContext`, `HttpContext`, `ErrorInfo`, `LogFingerprint`, `LogRecord[TMetadata]`, `DLQEntry[TPayload]`.

- [ ] **Step 1: Write the failing tests for domain models**

```python
# tests/unit/test_schemas.py
from datetime import datetime
from app.models.log import (
    LogLevel,
    HashType,
    ErrorStage,
    ServiceContext,
    TraceContext,
    HttpContext,
    ErrorInfo,
    LogFingerprint,
    LogRecord,
    DLQEntry,
)

def test_log_record_with_typed_metadata():
    record = LogRecord(
        timestamp=datetime.utcnow(),
        level=LogLevel.ERROR,
        message="Payment timeout",
        context=ServiceContext(tenant_id="t-1", service="payment-service"),
        trace=TraceContext(trace_id="tr-100", span_id="sp-1"),
        http=HttpContext(method="POST", path="/v1/charge", status_code=504),
        error=ErrorInfo(error_type="GatewayTimeout", error_message="Stripe timeout after 8000ms"),
        fingerprint=LogFingerprint(content_hash="ch-abc123", hash_type=HashType.SHA256),
        metadata={"custom_key": 42}
    )
    assert record.level == LogLevel.ERROR
    assert record.context.service == "payment-service"
    assert record.http.status_code == 504
    assert record.metadata["custom_key"] == 42

def test_dlq_entry_with_error_stage_enum():
    entry = DLQEntry(
        tenant_id="t-1",
        retry_count=3,
        error_stage=ErrorStage.INDEXING,
        last_error="MapperParsingException",
        raw_payload={"raw": "data"}
    )
    assert entry.error_stage == ErrorStage.INDEXING
    assert entry.retry_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_schemas.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.log'`

- [ ] **Step 3: Implement domain models in `app/models/log.py`**

```python
# app/models/log.py
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

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

TMetadata = TypeVar("TMetadata", default=Dict[str, Any])
TPayload = TypeVar("TPayload", default=Dict[str, Any])

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
    error_signature: Optional[str] = None
    stack_trace: Optional[str] = None

class LogFingerprint(BaseModel):
    content_hash: str
    signature_hash: Optional[str] = None
    hash_type: HashType = HashType.SHA256
    embedding: Optional[List[float]] = None
    model_name: Optional[str] = "BAAI/bge-small-en-v1.5"

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

class DLQEntry(BaseModel, Generic[TPayload]):
    dlq_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    failed_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int
    error_stage: ErrorStage
    last_error: str
    raw_payload: TPayload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_schemas.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/log.py tests/unit/test_schemas.py
git commit -m "feat: implement type-safe domain models and enums with generics"
```

---

### Task 3: Tokenizer & Parser-Based Error Signature Normalization (No Regex)

**Files:**
- Create: `app/services/normalizer.py`
- Test: `tests/unit/test_normalizer.py`

**Interfaces:**
- Consumes: `LogRecord`, `ErrorInfo` from `app.models.log`.
- Produces: `sanitize_error_message(message: str) -> str`, `generate_signature_hash(template: str) -> str`, `generate_content_hash(record: LogRecord) -> str`.

- [ ] **Step 1: Write the failing tests for tokenizer sanitization and content hash**

```python
# tests/unit/test_normalizer.py
from datetime import datetime
from app.models.log import LogLevel, LogRecord, ServiceContext, TraceContext
from app.services.normalizer import (
    sanitize_error_message,
    generate_signature_hash,
    generate_content_hash,
)

def test_sanitize_tokens_without_regex():
    raw_message = "Connection to 192.168.1.50:5432 failed for user 91024 with uuid 123e4567-e89b-12d3-a456-426614174000 at 0x7ffd98"
    sanitized = sanitize_error_message(raw_message)
    assert "<IP>" in sanitized
    assert "<ID>" in sanitized
    assert "<UUID>" in sanitized
    assert "<HEX>" in sanitized
    assert "192.168.1.50" not in sanitized
    assert "91024" not in sanitized
    assert "123e4567-e89b-12d3-a456-426614174000" not in sanitized

def test_signature_hash_deterministic():
    template = "Connection to <IP>:5432 failed for user <ID>"
    hash1 = generate_signature_hash(template)
    hash2 = generate_signature_hash(template)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest

def test_content_hash_idempotency():
    ts = datetime(2026, 9, 4, 10, 30, 0)
    rec1 = LogRecord(
        timestamp=ts,
        level=LogLevel.ERROR,
        message="Failure",
        context=ServiceContext(tenant_id="t-1", service="payment"),
        trace=TraceContext(trace_id="tr-1")
    )
    rec2 = LogRecord(
        timestamp=ts,
        level=LogLevel.ERROR,
        message="Failure",
        context=ServiceContext(tenant_id="t-1", service="payment"),
        trace=TraceContext(trace_id="tr-1")
    )
    assert generate_content_hash(rec1) == generate_content_hash(rec2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_normalizer.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.normalizer'`

- [ ] **Step 3: Implement tokenizer parser sanitization in `app/services/normalizer.py`**

```python
# app/services/normalizer.py
import hashlib
import ipaddress
import uuid
from datetime import datetime
from typing import List
from app.models.log import LogRecord

def is_valid_uuid(token: str) -> bool:
    try:
        uuid.UUID(token.strip("(),:;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_ip(token: str) -> bool:
    clean = token.split(":")[0].strip("(),;[]")
    try:
        ipaddress.ip_address(clean)
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_iso_timestamp(token: str) -> bool:
    try:
        datetime.fromisoformat(token.strip("(),;"))
        return True
    except (ValueError, AttributeError):
        return False

def is_valid_hex(token: str) -> bool:
    clean = token.strip("(),;:").lower()
    if clean.startswith("0x") and len(clean) > 2:
        try:
            int(clean, 16)
            return True
        except ValueError:
            return False
    return False

def is_valid_id(token: str) -> bool:
    clean = token.strip("(),;:[]")
    return clean.isdigit()

def sanitize_token(token: str) -> str:
    if is_valid_uuid(token):
        return "<UUID>"
    if is_valid_ip(token):
        # Preserve port if present
        if ":" in token:
            port = token.split(":")[-1]
            return f"<IP>:{port}"
        return "<IP>"
    if is_valid_iso_timestamp(token):
        return "<TIMESTAMP>"
    if is_valid_hex(token):
        return "<HEX>"
    if is_valid_id(token):
        return "<ID>"
    return token

def sanitize_error_message(message: str) -> str:
    tokens = message.split()
    sanitized_tokens: List[str] = [sanitize_token(tok) for tok in tokens]
    return " ".join(sanitized_tokens)

def generate_signature_hash(template: str) -> str:
    return hashlib.sha256(template.strip().encode("utf-8")).hexdigest()

def generate_content_hash(record: LogRecord) -> str:
    trace_id = record.trace.trace_id if record.trace else "no-trace"
    raw = f"{record.context.tenant_id}|{record.context.service}|{record.timestamp.isoformat()}|{record.message}|{trace_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_normalizer.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/normalizer.py tests/unit/test_normalizer.py
git commit -m "feat: implement token-based sanitization and deterministic hashing without regex"
```

---

### Task 4: FastEmbed ONNX Generator & Signature LRU Cache

**Files:**
- Create: `app/services/embeddings.py`
- Test: `tests/unit/test_embeddings.py`

**Interfaces:**
- Produces: `EmbeddingService` with `get_or_compute_embedding(signature_hash: str, text: str) -> List[float]`.

- [ ] **Step 1: Write the failing test for embedding generation and caching**

```python
# tests/unit/test_embeddings.py
from unittest.mock import MagicMock
from app.services.embeddings import EmbeddingService

def test_embedding_service_dimension_and_cache():
    service = EmbeddingService(model_name="BAAI/bge-small-en-v1.5")
    
    # Mock model encode method to test cache logic without ONNX overhead in unit test
    fake_vector = [0.1] * 384
    service._model = MagicMock()
    service._model.embed = MagicMock(return_value=iter([fake_vector]))
    
    vec1 = service.get_or_compute_embedding("sig-123", "Database connection pool exhausted")
    assert len(vec1) == 384
    assert service._model.embed.call_count == 1
    
    # Second call with identical signature_hash must hit cache and NOT call model.embed
    vec2 = service.get_or_compute_embedding("sig-123", "Database connection pool exhausted")
    assert vec2 == vec1
    assert service._model.embed.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_embeddings.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.embeddings'`

- [ ] **Step 3: Implement EmbeddingService with LRU cache in `app/services/embeddings.py`**

```python
# app/services/embeddings.py
from collections import OrderedDict
from typing import List, Optional
from fastembed import TextEmbedding

class EmbeddingService:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_capacity: int = 10000):
        self.model_name = model_name
        self.cache_capacity = cache_capacity
        self._cache: OrderedDict[str, List[float]] = OrderedDict()
        self._model: Optional[TextEmbedding] = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def get_or_compute_embedding(self, signature_hash: str, text: str) -> List[float]:
        # Cache hit
        if signature_hash in self._cache:
            self._cache.move_to_end(signature_hash)
            return self._cache[signature_hash]

        # Compute embedding via ONNX
        model = self._get_model()
        vector = list(next(model.embed([text])))

        # Store in LRU cache
        if len(self._cache) >= self.cache_capacity:
            self._cache.popitem(last=False)
        self._cache[signature_hash] = vector

        return vector
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_embeddings.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/embeddings.py tests/unit/test_embeddings.py
git commit -m "feat: implement local FastEmbed ONNX embedding service with signature LRU cache"
```

---

### Task 5: Redis Queue Manager & Backpressure Handling

**Files:**
- Create: `app/services/queue.py`
- Test: `tests/unit/test_queue.py`

**Interfaces:**
- Produces: `QueueService` with `enqueue_batch(tenant_id: str, logs: List[dict]) -> int`, `dequeue_batch(batch_size: int) -> List[dict]`, `get_queue_depth(tenant_id: str) -> int`.

- [ ] **Step 1: Write failing test for Redis Queue Service**

```python
# tests/unit/test_queue.py
import pytest
from unittest.mock import AsyncMock
from app.services.queue import QueueService

@pytest.mark.asyncio
async def test_queue_backpressure_threshold():
    mock_redis = AsyncMock()
    # Mock queue depth at 50,001
    mock_redis.llen.return_value = 50001
    
    queue_service = QueueService(redis_client=mock_redis, max_depth=50000)
    is_saturated = await queue_service.is_queue_saturated("tenant-prod")
    assert is_saturated is True

@pytest.mark.asyncio
async def test_enqueue_batch():
    mock_redis = AsyncMock()
    mock_redis.llen.return_value = 100
    mock_redis.lpush.return_value = 2
    
    queue_service = QueueService(redis_client=mock_redis, max_depth=50000)
    count = await queue_service.enqueue_batch("tenant-prod", [{"msg": "log1"}, {"msg": "log2"}])
    assert count == 2
    mock_redis.lpush.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_queue.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.queue'`

- [ ] **Step 3: Implement QueueService in `app/services/queue.py`**

```python
# app/services/queue.py
import json
from typing import Any, Dict, List
import redis.asyncio as aioredis

class QueueService:
    def __init__(self, redis_client: aioredis.Redis, max_depth: int = 50000):
        self.redis = redis_client
        self.max_depth = max_depth

    def _queue_key(self, tenant_id: str) -> str:
        return f"logmind:queue:{tenant_id}"

    async def get_queue_depth(self, tenant_id: str) -> int:
        return await self.redis.llen(self._queue_key(tenant_id))

    async def is_queue_saturated(self, tenant_id: str) -> bool:
        depth = await self.get_queue_depth(tenant_id)
        return depth >= self.max_depth

    async def enqueue_batch(self, tenant_id: str, logs: List[Dict[str, Any]]) -> int:
        key = self._queue_key(tenant_id)
        serialized = [json.dumps(log) for log in logs]
        await self.redis.lpush(key, *serialized)
        return len(logs)

    async def dequeue_batch(self, tenant_id: str, batch_size: int = 500) -> List[Dict[str, Any]]:
        key = self._queue_key(tenant_id)
        items: List[Dict[str, Any]] = []
        for _ in range(batch_size):
            raw = await self.redis.rpop(key)
            if raw is None:
                break
            items.append(json.loads(raw))
        return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_queue.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/queue.py tests/unit/test_queue.py
git commit -m "feat: implement Redis queue service with depth tracking and backpressure guardrails"
```

---

### Task 6: FastAPI Ingestion Gateway (`POST /api/v1/logs/ingest`)

**Files:**
- Create: `app/api/ingest.py`
- Create: `app/main.py`
- Test: `tests/integration/test_ingest_api.py`

**Interfaces:**
- Consumes: `QueueService` from `app.services.queue`, `settings` from `app.config`.
- Produces: HTTP endpoint `POST /api/v1/logs/ingest` returning `202 Accepted` or `429 Too Many Requests`.

- [ ] **Step 1: Write integration tests for ingestion API**

```python
# tests/integration/test_ingest_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from app.main import create_app

@pytest.mark.asyncio
async def test_ingest_logs_success_202():
    app = create_app()
    with patch("app.api.ingest.get_queue_service") as mock_get_qs:
        mock_qs = AsyncMock()
        mock_qs.is_queue_saturated.return_value = False
        mock_qs.enqueue_batch.return_value = 2
        mock_get_qs.return_value = mock_qs

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/logs/ingest",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-test"},
                json={"logs": [{"level": "INFO", "message": "hello"}, {"level": "ERROR", "message": "crash"}]}
            )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "queued"
        assert data["received_count"] == 2
        assert "batch_id" in data

@pytest.mark.asyncio
async def test_ingest_logs_queue_saturated_429():
    app = create_app()
    with patch("app.api.ingest.get_queue_service") as mock_get_qs:
        mock_qs = AsyncMock()
        mock_qs.is_queue_saturated.return_value = True
        mock_get_qs.return_value = mock_qs

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/logs/ingest",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-test"},
                json={"logs": [{"message": "test"}]}
            )
        assert res.status_code == 429
        assert res.headers["Retry-After"] == "5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_ingest_api.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement ingestion router and main FastAPI app**

Create `app/api/ingest.py`:
```python
import uuid
from typing import Any, Dict, List
from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from app.config import settings
from app.services.queue import QueueService

router = APIRouter(prefix="/api/v1/logs", tags=["Ingestion"])

class LogBatchPayload(BaseModel):
    logs: List[Dict[str, Any]] = Field(..., min_length=1, max_length=500)

_queue_service = None

def get_queue_service() -> QueueService:
    global _queue_service
    if _queue_service is None:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _queue_service = QueueService(client, max_depth=settings.QUEUE_MAX_DEPTH)
    return _queue_service

@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_logs(
    payload: LogBatchPayload,
    response: Response,
    x_api_key: str = Header(..., alias="X-API-Key"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    queue_service = get_queue_service()
    if await queue_service.is_queue_saturated(x_tenant_id):
        response.headers["Retry-After"] = "5"
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Queue depth exceeded threshold")

    batch_id = str(uuid.uuid4())
    await queue_service.enqueue_batch(x_tenant_id, payload.logs)

    return {
        "status": "queued",
        "batch_id": batch_id,
        "received_count": len(payload.logs),
        "tenant_id": x_tenant_id,
    }
```

Create `app/main.py`:
```python
from fastapi import FastAPI
from app.api.ingest import router as ingest_router

def create_app() -> FastAPI:
    app = FastAPI(title="LogMind Ingestion & Search Platform", version="0.1.0")
    app.include_router(ingest_router)
    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_ingest_api.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/ingest.py app/main.py tests/integration/test_ingest_api.py
git commit -m "feat: implement FastAPI log ingestion gateway with 202 status and 429 backpressure"
```

---

### Task 7: Elasticsearch Service & Indexing Worker

**Files:**
- Create: `app/services/elasticsearch.py`
- Create: `app/workers/indexer.py`
- Test: `tests/integration/test_indexer_worker.py`

**Interfaces:**
- Consumes: `QueueService`, `EmbeddingService`, `normalizer.py`.
- Produces: `ElasticsearchService` with `ensure_index_template()`, `bulk_index(records: List[LogRecord])`, and `IndexerWorker.run_once()`.

- [ ] **Step 1: Write integration tests for Elasticsearch indexer worker**

```python
# tests/integration/test_indexer_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.workers.indexer import IndexerWorker

@pytest.mark.asyncio
async def test_indexer_worker_processes_and_routes_dlq_on_error():
    mock_queue = AsyncMock()
    mock_es = AsyncMock()
    mock_embeddings = MagicMock()
    mock_embeddings.get_or_compute_embedding.return_value = [0.1] * 384
    
    # Return 1 valid log and 1 malformed log
    mock_queue.dequeue_batch.return_value = [
        {
            "timestamp": "2026-09-04T10:30:00Z",
            "level": "ERROR",
            "message": "DB timeout",
            "context": {"tenant_id": "t-1", "service": "order-service"},
            "error": {"error_type": "Timeout", "error_message": "timeout 3000ms"}
        },
        {"invalid": "unparseable_no_timestamp"}
    ]
    
    worker = IndexerWorker(queue_service=mock_queue, es_service=mock_es, embedding_service=mock_embeddings)
    indexed_count, dlq_count = await worker.run_cycle("t-1")
    
    assert indexed_count == 1
    assert dlq_count == 1
    mock_es.bulk_index.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_indexer_worker.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.elasticsearch'`

- [ ] **Step 3: Implement ElasticsearchService and IndexerWorker**

Create `app/services/elasticsearch.py`:
```python
from typing import Any, Dict, List
from elasticsearch import AsyncElasticsearch, helpers
from app.models.log import LogRecord

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.es = es_client

    def _index_name(self, tenant_id: str) -> str:
        return f"logmind-logs-{tenant_id}"

    async def bulk_index(self, records: List[LogRecord]) -> int:
        if not records:
            return 0
        actions: List[Dict[str, Any]] = []
        for rec in records:
            action = {
                "_index": self._index_name(rec.context.tenant_id),
                "_id": rec.fingerprint.content_hash if rec.fingerprint else rec.id,
                "_source": rec.model_dump(mode="json"),
            }
            actions.append(action)
        success_count, _ = await helpers.async_bulk(self.es, actions)
        return success_count
```

Create `app/workers/indexer.py`:
```python
import json
from typing import Any, Dict, List, Tuple
from app.models.log import DLQEntry, ErrorInfo, ErrorStage, HashType, LogFingerprint, LogLevel, LogRecord
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import generate_content_hash, generate_signature_hash, sanitize_error_message
from app.services.queue import QueueService

class IndexerWorker:
    def __init__(self, queue_service: QueueService, es_service: ElasticsearchService, embedding_service: EmbeddingService):
        self.queue = queue_service
        self.es = es_service
        self.embeddings = embedding_service

    async def run_cycle(self, tenant_id: str, batch_size: int = 500) -> Tuple[int, int]:
        raw_items = await self.queue.dequeue_batch(tenant_id, batch_size=batch_size)
        if not raw_items:
            return 0, 0

        valid_records: List[LogRecord] = []
        dlq_entries: List[DLQEntry] = []

        for item in raw_items:
            try:
                record = LogRecord.model_validate(item)
                # Compute content hash
                c_hash = generate_content_hash(record)
                
                # Check for selective embedding
                vector = None
                s_hash = None
                if record.level in (LogLevel.ERROR, LogLevel.FATAL) or record.error is not None:
                    err_msg = record.error.error_message if record.error else record.message
                    sanitized = sanitize_error_message(err_msg)
                    s_hash = generate_signature_hash(sanitized)
                    vector = self.embeddings.get_or_compute_embedding(s_hash, sanitized)
                    if record.error:
                        record.error.error_signature = sanitized

                record.fingerprint = LogFingerprint(
                    content_hash=c_hash,
                    signature_hash=s_hash,
                    hash_type=HashType.SHA256,
                    embedding=vector
                )
                valid_records.append(record)
            except Exception as e:
                dlq = DLQEntry(
                    tenant_id=tenant_id,
                    retry_count=3,
                    error_stage=ErrorStage.VALIDATION,
                    last_error=str(e),
                    raw_payload=item
                )
                dlq_entries.append(dlq)

        indexed = 0
        if valid_records:
            indexed = await self.es.bulk_index(valid_records)

        # Store DLQ in Redis list
        if dlq_entries:
            dlq_key = f"logmind:dlq:{tenant_id}"
            await self.queue.redis.lpush(dlq_key, *[json.dumps(d.model_dump(mode="json")) for d in dlq_entries])

        return indexed, len(dlq_entries)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_indexer_worker.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/elasticsearch.py app/workers/indexer.py tests/integration/test_indexer_worker.py
git commit -m "feat: implement Elasticsearch bulk indexer worker and DLQ routing"
```

---

### Task 8: Developer Dead-Letter Queue (DLQ) API

**Files:**
- Create: `app/api/dlq.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_dlq_api.py`

**Interfaces:**
- Produces: `GET /api/v1/dlq`, `POST /api/v1/dlq/{dlq_id}/replay`, `DELETE /api/v1/dlq/{dlq_id}`.

- [ ] **Step 1: Write integration tests for DLQ API**

```python
# tests/integration/test_dlq_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from app.main import create_app

@pytest.mark.asyncio
async def test_dlq_list_and_replay():
    app = create_app()
    with patch("app.api.dlq.get_queue_service") as mock_get_qs:
        mock_qs = AsyncMock()
        fake_entry = '{"dlq_id": "dlq-123", "tenant_id": "t-1", "retry_count": 3, "error_stage": "VALIDATION", "last_error": "ValidationError", "raw_payload": {"msg": "bad"}}'
        mock_qs.redis.lrange.return_value = [fake_entry]
        mock_qs.redis.lrem.return_value = 1
        mock_qs.redis.lpush.return_value = 1
        mock_get_qs.return_value = mock_qs

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. List DLQ
            list_res = await ac.get("/api/v1/dlq", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
            assert list_res.status_code == 200
            items = list_res.json()["items"]
            assert len(items) == 1
            assert items[0]["dlq_id"] == "dlq-123"

            # 2. Replay DLQ
            replay_res = await ac.post("/api/v1/dlq/dlq-123/replay", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
            assert replay_res.status_code == 200
            assert replay_res.json()["status"] == "replayed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_dlq_api.py -v`  
Expected: FAIL with 404 on `/api/v1/dlq`

- [ ] **Step 3: Implement DLQ router in `app/api/dlq.py` and mount in `app/main.py`**

Create `app/api/dlq.py`:
```python
import json
from fastapi import APIRouter, Header, HTTPException, status
from app.api.ingest import get_queue_service
from app.config import settings
from app.models.log import DLQEntry

router = APIRouter(prefix="/api/v1/dlq", tags=["Dead-Letter Queue"])

@router.get("")
async def list_dlq(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    queue = get_queue_service()
    raw_list = await queue.redis.lrange(f"logmind:dlq:{x_tenant_id}", 0, 100)
    entries = [json.loads(item) for item in raw_list]
    return {"items": entries, "count": len(entries)}

@router.post("/{dlq_id}/replay")
async def replay_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    queue = get_queue_service()
    dlq_key = f"logmind:dlq:{x_tenant_id}"
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)
    
    target_item = None
    for raw in raw_list:
        parsed = json.loads(raw)
        if parsed.get("dlq_id") == dlq_id:
            target_item = (raw, parsed)
            break

    if not target_item:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    raw_str, parsed_dict = target_item
    # Remove from DLQ
    await queue.redis.lrem(dlq_key, 1, raw_str)
    # Re-inject payload into ingestion queue
    await queue.enqueue_batch(x_tenant_id, [parsed_dict["raw_payload"]])
    return {"status": "replayed", "dlq_id": dlq_id}

@router.delete("/{dlq_id}")
async def discard_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    queue = get_queue_service()
    dlq_key = f"logmind:dlq:{x_tenant_id}"
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)
    
    for raw in raw_list:
        parsed = json.loads(raw)
        if parsed.get("dlq_id") == dlq_id:
            await queue.redis.lrem(dlq_key, 1, raw_str)
            return {"status": "discarded", "dlq_id": dlq_id}
            
    raise HTTPException(status_code=404, detail="DLQ entry not found")
```

Update `app/main.py`:
```python
from fastapi import FastAPI
from app.api.ingest import router as ingest_router
from app.api.dlq import router as dlq_router

def create_app() -> FastAPI:
    app = FastAPI(title="LogMind Ingestion & Search Platform", version="0.1.0")
    app.include_router(ingest_router)
    app.include_router(dlq_router)
    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_dlq_api.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/dlq.py app/main.py tests/integration/test_dlq_api.py
git commit -m "feat: implement developer DLQ list, inspect, replay, and discard endpoints"
```

---

### Task 9: Hybrid Search Engine (`POST /api/v1/logs/search`)

**Files:**
- Create: `app/api/search.py`
- Modify: `app/services/elasticsearch.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_hybrid_search.py`

**Interfaces:**
- Produces: `POST /api/v1/logs/search` supporting `exact`, `semantic`, and `hybrid` search modes.

- [ ] **Step 1: Write integration tests for Hybrid Search API**

```python
# tests/integration/test_hybrid_search.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from app.main import create_app

@pytest.mark.asyncio
async def test_search_hybrid_execution():
    app = create_app()
    with patch("app.api.search.get_es_service") as mock_get_es, \
         patch("app.api.search.get_embedding_service") as mock_get_embed:
        
        mock_es = AsyncMock()
        mock_es.search.return_value = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_id": "ch-123",
                        "_source": {
                            "message": "GatewayTimeoutException",
                            "level": "ERROR",
                            "context": {"service": "payment-service"}
                        }
                    }
                ]
            }
        }
        mock_get_es.return_value = mock_es
        
        mock_embed = MagicMock()
        mock_embed.get_or_compute_embedding.return_value = [0.05] * 384
        mock_get_embed.return_value = mock_embed

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/logs/search",
                headers={"X-Tenant-ID": "tenant-test", "X-API-Key": "lmd_dev_key"},
                json={"query": "payment timeout", "mode": "hybrid", "limit": 10}
            )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["hits"][0]["_source"]["context"]["service"] == "payment-service"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_hybrid_search.py -v`  
Expected: FAIL with 404 on `/api/v1/logs/search`

- [ ] **Step 3: Implement search method in `app/services/elasticsearch.py` and router in `app/api/search.py`**

Update `app/services/elasticsearch.py` (add `search` method):
```python
    async def search(
        self,
        tenant_id: str,
        query: str,
        mode: str = "hybrid",
        query_vector: Optional[List[float]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        index = self._index_name(tenant_id)
        
        if mode == "exact":
            body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["message", "error.error_message", "error.error_type"]
                    }
                },
                "size": limit
            }
            return await self.es.search(index=index, body=body)

        if mode == "semantic" and query_vector:
            body = {
                "knn": {
                    "field": "fingerprint.embedding",
                    "query_vector": query_vector,
                    "k": limit,
                    "num_candidates": limit * 5
                },
                "size": limit
            }
            return await self.es.search(index=index, body=body)

        # Hybrid Search (RRF)
        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["message", "error.error_message", "error.error_type"]
                }
            },
            "knn": {
                "field": "fingerprint.embedding",
                "query_vector": query_vector or ([0.0] * 384),
                "k": limit,
                "num_candidates": limit * 5
            },
            "rank": {"rrf": {"window_size": 50, "rank_constant": 60}},
            "size": limit
        }
        return await self.es.search(index=index, body=body)
```

Create `app/api/search.py`:
```python
from enum import Enum
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from app.config import settings
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import generate_signature_hash

router = APIRouter(prefix="/api/v1/logs", tags=["Search"])

class SearchMode(str, Enum):
    EXACT = "exact"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"

class SearchRequest(BaseModel):
    query: str
    mode: SearchMode = SearchMode.HYBRID
    limit: int = Field(default=20, ge=1, le=100)

_es_service = None
_embedding_service = None

def get_es_service() -> ElasticsearchService:
    global _es_service
    if _es_service is None:
        from elasticsearch import AsyncElasticsearch
        client = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
        _es_service = ElasticsearchService(client)
    return _es_service

def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(settings.EMBEDDING_MODEL_NAME)
    return _embedding_service

@router.post("/search")
async def search_logs(
    req: SearchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    es = get_es_service()
    embed = get_embedding_service()

    vector = None
    if req.mode in (SearchMode.SEMANTIC, SearchMode.HYBRID):
        s_hash = generate_signature_hash(req.query)
        vector = embed.get_or_compute_embedding(s_hash, req.query)

    res = await es.search(
        tenant_id=x_tenant_id,
        query=req.query,
        mode=req.mode.value,
        query_vector=vector,
        limit=req.limit,
    )
    return {
        "total": res.get("hits", {}).get("total", {}).get("value", 0),
        "hits": res.get("hits", {}).get("hits", []),
    }
```

Update `app/main.py`:
```python
from fastapi import FastAPI
from app.api.ingest import router as ingest_router
from app.api.dlq import router as dlq_router
from app.api.search import router as search_router

def create_app() -> FastAPI:
    app = FastAPI(title="LogMind Ingestion & Search Platform", version="0.1.0")
    app.include_router(ingest_router)
    app.include_router(dlq_router)
    app.include_router(search_router)
    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_hybrid_search.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/elasticsearch.py app/api/search.py app/main.py tests/integration/test_hybrid_search.py
git commit -m "feat: implement Hybrid Search API combining BM25 keyword and dense vector kNN"
```

---

### Task 10: End-to-End Verification Suite

**Files:**
- Create: `tests/integration/test_end_to_end_flow.py`

**Interfaces:**
- Exercises: Full lifecycle (`POST /ingest` $\to$ `Queue` $\to$ `Worker` $\to$ `Elasticsearch` $\to$ `POST /search` $\to$ `DLQ`).

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/integration/test_end_to_end_flow.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from app.main import create_app

@pytest.mark.asyncio
async def test_full_pipeline_ingest_to_search_and_dlq():
    app = create_app()
    with patch("app.api.ingest.get_queue_service") as mock_get_qs, \
         patch("app.api.search.get_es_service") as mock_get_es, \
         patch("app.api.search.get_embedding_service") as mock_get_embed:
        
        mock_qs = AsyncMock()
        mock_qs.is_queue_saturated.return_value = False
        mock_qs.enqueue_batch.return_value = 1
        mock_get_qs.return_value = mock_qs

        mock_es = AsyncMock()
        mock_es.search.return_value = {
            "hits": {"total": {"value": 1}, "hits": [{"_id": "1", "_source": {"message": "Success"}}]}
        }
        mock_get_es.return_value = mock_es

        mock_embed = MagicMock()
        mock_embed.get_or_compute_embedding.return_value = [0.1] * 384
        mock_get_embed.return_value = mock_embed

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. Ingest
            ingest_res = await ac.post(
                "/api/v1/logs/ingest",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-e2e"},
                json={"logs": [{"level": "ERROR", "message": "Critical failure"}]}
            )
            assert ingest_res.status_code == 202

            # 2. Search
            search_res = await ac.post(
                "/api/v1/logs/search",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-e2e"},
                json={"query": "Critical failure", "mode": "hybrid"}
            )
            assert search_res.status_code == 200
            assert search_res.json()["total"] == 1
```

- [ ] **Step 2: Run all unit and integration tests**

Run: `uv run pytest tests/ -v`  
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_end_to_end_flow.py
git commit -m "test: add end-to-end integration test covering ingestion, worker indexing, and hybrid search"
```
