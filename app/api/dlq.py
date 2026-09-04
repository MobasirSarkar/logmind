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
            await queue.redis.lrem(dlq_key, 1, raw)
            return {"status": "discarded", "dlq_id": dlq_id}
            
    raise HTTPException(status_code=404, detail="DLQ entry not found")
