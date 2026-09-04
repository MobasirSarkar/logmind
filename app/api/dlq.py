import json
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from app.api.ingest import get_queue_service
from app.config import settings

router = APIRouter(prefix="/api/v1/dlq", tags=["Dead-Letter Queue"])

def _verify_auth(x_api_key: str) -> None:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

@router.get("")
async def list_dlq(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    _verify_auth(x_api_key)
    queue = get_queue_service()
    raw_list = await queue.redis.lrange(f"logmind:dlq:{x_tenant_id}", 0, 100)
    entries: list[dict[str, Any]] = []
    for item in raw_list:
        try:
            entries.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            entries.append({"raw": str(item), "parse_error": True})
    return {"items": entries, "count": len(entries)}

@router.get("/{dlq_id}")
async def get_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    _verify_auth(x_api_key)
    queue = get_queue_service()
    raw_list = await queue.redis.lrange(f"logmind:dlq:{x_tenant_id}", 0, 500)
    for raw in raw_list:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("dlq_id") == dlq_id:
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    raise HTTPException(status_code=404, detail="DLQ entry not found")

@router.post("/{dlq_id}/replay")
async def replay_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    _verify_auth(x_api_key)
    queue = get_queue_service()
    dlq_key = f"logmind:dlq:{x_tenant_id}"
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)

    target_raw = None
    payload_to_replay = None
    for raw in raw_list:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("dlq_id") == dlq_id:
                target_raw = raw
                payload_to_replay = parsed.get("raw_payload", parsed)
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if target_raw is None or payload_to_replay is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    # Remove from DLQ
    await queue.redis.lrem(dlq_key, 1, target_raw)
    # Re-inject payload into ingestion queue
    await queue.enqueue_batch(x_tenant_id, [payload_to_replay])
    return {"status": "replayed", "dlq_id": dlq_id}

@router.delete("/{dlq_id}")
async def discard_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    _verify_auth(x_api_key)
    queue = get_queue_service()
    dlq_key = f"logmind:dlq:{x_tenant_id}"
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)

    for raw in raw_list:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("dlq_id") == dlq_id:
                await queue.redis.lrem(dlq_key, 1, raw)
                return {"status": "discarded", "dlq_id": dlq_id}
        except (json.JSONDecodeError, TypeError):
            continue

    raise HTTPException(status_code=404, detail="DLQ entry not found")
