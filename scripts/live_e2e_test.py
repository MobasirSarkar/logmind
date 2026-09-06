import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_embedding_service,
    get_es_service,
    get_queue_service,
)
from app.db import get_datastore
from app.main import create_app
from app.workers.indexer import IndexerWorker
from simulator.scenarios import generate_payment_timeout_scenario


async def run_live_e2e():
    print("=" * 60)
    print("LOGMIND LIVE COMPLETE END-TO-END SYSTEM TEST")
    print("=" * 60)

    app = create_app()
    tenant_id = f"live-test-{uuid.uuid4().hex[:6]}"
    api_key = "lmd_dev_key"
    headers = {
        "X-Tenant-ID": tenant_id,
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    print(
        f"\n[1/7] Initializing Datastores & Checking Connectivity (tenant: {tenant_id})"
    )
    es_service = get_es_service()
    await es_service.ensure_index_template()
    queue_service = get_queue_service()
    await queue_service.redis.ping()
    datastore = get_datastore()
    await datastore.ensure_tables()
    embed_service = get_embedding_service()
    print("  -> Elasticsearch, Redis, PostgreSQL, and Embeddings connected.")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8000",
        timeout=120.0,
    ) as client:
        print("\n[2/7] Registering Service Topology Dependencies")
        r1 = await client.post(
            "/api/v1/topology/dependencies",
            headers=headers,
            json={
                "source_service": "api-gateway",
                "target_service": "order-service",
                "dependency_type": "HTTP",
            },
        )
        assert r1.status_code == 200, f"Failed topology 1: {r1.text}"

        r2 = await client.post(
            "/api/v1/topology/dependencies",
            headers=headers,
            json={
                "source_service": "order-service",
                "target_service": "payment-service",
                "dependency_type": "HTTP",
            },
        )
        assert r2.status_code == 200, f"Failed topology 2: {r2.text}"
        print("  -> Topology saved: api-gateway -> order-service -> payment-service")

        print("\n[3/7] Ingesting Payment Service Troubleshooting Runbook")
        rb_res = await client.post(
            "/api/v1/runbooks",
            headers=headers,
            json={
                "service": "payment-service",
                "title": "Stripe Gateway Timeout Troubleshooting",
                "content": "When payment-service encounters GatewayTimeoutException with Stripe, inspect upstream Stripe latency, verify webhook retries, and check circuit breaker configuration.",
            },
        )
        assert rb_res.status_code == 200, f"Failed runbook ingest: {rb_res.text}"
        print("  -> Runbook ingested into Elasticsearch vector store.")

        print("\n[4/7] Ingesting Synthetic Incident Logs into Redis Queue")
        # Base time set in the recent past so timeline completes before evaluate call
        scenario_base_time = datetime.now(UTC) - timedelta(seconds=20)
        logs, _scenario_record = generate_payment_timeout_scenario(
            tenant_id=tenant_id, base_time=scenario_base_time
        )
        ingest_res = await client.post(
            "/api/v1/logs/ingest",
            headers=headers,
            json={"logs": logs},
        )
        assert ingest_res.status_code == 202, f"Ingest failed: {ingest_res.text}"
        print(f"  -> Ingested {len(logs)} logs via POST /api/v1/logs/ingest.")

        print("\n[5/7] Running Worker Cycle (Redis Dequeue -> Enrich -> ES Bulk Index)")
        worker = IndexerWorker(queue_service, es_service, embed_service)
        indexed, dlq = await worker.run_cycle(tenant_id)
        assert indexed > 0, "No logs were indexed into Elasticsearch"
        await es_service.es.indices.refresh(index=f"logmind-logs-{tenant_id}")
        print(
            f"  -> Worker completed cycle: {indexed} logs indexed to Elasticsearch, {dlq} to DLQ."
        )

        print("\n[6/7] Evaluating Incidents (POST /api/v1/incidents/evaluate)")
        eval_res = await client.post(
            "/api/v1/incidents/evaluate",
            headers=headers,
            json={"lookback_seconds": 300, "min_error_count": 1},
        )
        assert eval_res.status_code == 200, f"Evaluate failed: {eval_res.text}"
        incidents = eval_res.json()["data"]["items"]
        assert len(incidents) >= 1, (
            f"Expected at least 1 incident, got {len(incidents)}"
        )
        target_incident = incidents[0]
        incident_id = target_incident["incident_id"]
        print(f"  -> Incident detected: {incident_id}")
        print(f"     Title: {target_incident['title']}")
        print(f"     Trigger Service: {target_incident['trigger_service']}")
        print(f"     Affected Services: {target_incident['affected_services']}")
        print(
            f"     Events: {len(target_incident['events'])} timeline events correlated"
        )

        print(
            "\n[7/7] Starting Live AI Investigation (POST /api/v1/investigations/{incident_id}/start)"
        )
        print("     Model: minimax/minimax-m3:free via OpenRouter")
        inv_res = await client.post(
            f"/api/v1/investigations/{incident_id}/start",
            headers=headers,
        )
        assert inv_res.status_code == 200, f"Investigation failed: {inv_res.text}"
        report = inv_res.json()["data"]
        print(f"  -> Status: {report['status']}")
        print(f"     Fallback: {report['is_fallback']}")
        print(f"     Confidence Score: {report['confidence_score']}")
        print(f"     Summary:\n       {report['summary']}")
        print(f"     Suspected Root Cause:\n       {report['suspected_root_cause']}")
        print("     Recommended Actions:")
        for action in report["recommended_actions"]:
            print(f"       * {action}")
        print(f"     Evidence Citations ({len(report['evidence'])} items):")
        for ev in report["evidence"]:
            print(
                f"       * [{ev['evidence_type']}] {ev['service']}: {ev['excerpt'][:120]}"
            )

        steps_res = await client.get(
            f"/api/v1/investigations/{incident_id}/steps",
            headers=headers,
        )
        assert steps_res.status_code == 200
        steps = steps_res.json()["data"]["steps"]
        print(f"  -> Autonomous Tool Loop Steps Executed by LLM: {len(steps)}")
        for st in steps:
            print(
                f"       Step {st['step_number']}: Tool={st['tool_name']} ({st['duration_ms']}ms)"
            )

    print("\n" + "=" * 60)
    print("ALL LIVE END-TO-END ACCEPTANCE CRITERIA PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_live_e2e())
