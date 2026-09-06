# LogMind

LogMind is an automated incident detection and root-cause analysis platform for distributed systems. It ingests logs into a queue, indexes them into Elasticsearch with semantic embeddings, correlates cascading failures across services, and runs an AI agent to diagnose the root cause with concrete evidence.

## System Architecture

```mermaid
flowchart LR
    subgraph Ingestion
        A[Microservices] -->|POST /logs/ingest| B[(Redis Queue)]
        B --> C[Indexer Worker]
    end

    subgraph Storage
        C --> D[(Elasticsearch)]
        C --> E[(Dead Letter Queue)]
        F[(PostgreSQL)]
    end

    subgraph Analysis
        D --> G[Correlation Engine]
        F --> G
        G -->|Detects Incidents| F
        G --> H[AI Investigation Agent]
        D -->|Tool Queries| H
        F -->|Topology & History| H
        H -->|Diagnosis| I[OpenRouter / LLM]
    end
```

## Prerequisites

Before running this project, make sure you have the following installed:

- Python 3.12 or newer
- uv (Python package manager)
- Docker and Docker Compose
- An OpenRouter API key (tested with free model: minimax/minimax-m3:free)

## Getting Started

### 1. Configure the Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Open `.env` and set your configuration:

```env
REDIS_URL=redis://localhost:6379/0
ELASTICSEARCH_URL=http://localhost:9200
DATABASE_URL=postgresql+asyncpg://logmind:logmind@localhost:5432/logmind
API_KEY=lmd_dev_key

# OpenRouter configuration for AI investigation
LLM_KEY=your-openrouter-api-key-here
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=minimax/minimax-m3:free
```

### 2. Start the Datastores

Start PostgreSQL, Redis, and Elasticsearch containers using Docker:

```bash
docker compose up -d
```

Verify that all three containers are running:

```bash
docker compose ps
```

### 3. Install Dependencies

Install all Python dependencies using uv:

```bash
uv sync
```

### 4. Start the Application

Start the FastAPI application with uvicorn:

```bash
uv run uvicorn app.main:create_app --factory --reload --port 8000
```

The server will be available at `http://127.0.0.1:8000`. Database tables and Elasticsearch index templates are created automatically on startup.

## Testing the System

### Run Automated Tests

Run the test suite across all services:

```bash
uv run pytest
```

### Run Live End-to-End Simulation

Run the live test script against your running datastores and OpenRouter:

```bash
uv run python scripts/live_e2e_test.py
```

This test executes the full lifecycle:
1. Registers service topology in PostgreSQL.
2. Ingests a troubleshooting runbook into Elasticsearch.
3. Generates a synthetic payment timeout incident and queues it in Redis.
4. Processes the queue with the background worker and indexes logs into Elasticsearch.
5. Evaluates error spikes and creates the incident record in PostgreSQL.
6. Runs the AI agent through live tool calls to find the root cause and print the diagnosis.

## Quick API Usage

### 1. Ingest Logs

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/logs/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: lmd_dev_key" \
  -H "X-Tenant-ID: tenant-default" \
  -d '{
    "logs": [
      {
        "timestamp": "2026-09-06T12:00:00Z",
        "level": "ERROR",
        "message": "Stripe upstream timed out after 8000ms",
        "service": "payment-service"
      }
    ]
  }'
```

### 2. Evaluate Incidents

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/incidents/evaluate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: lmd_dev_key" \
  -H "X-Tenant-ID: tenant-default" \
  -d "{\"lookback_seconds\": 300, \"min_error_count\": 1}"
```

### 3. Start AI Investigation

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/investigations/<INCIDENT_ID>/start" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: lmd_dev_key" \
  -H "X-Tenant-ID: tenant-default"
```

### 4. Inspect Investigation Steps

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/investigations/<INCIDENT_ID>/steps" \
  -H "X-API-Key: lmd_dev_key" \
  -H "X-Tenant-ID: tenant-default"
```
