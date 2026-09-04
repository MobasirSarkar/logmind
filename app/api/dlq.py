import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.api.deps import get_queue_service, verify_api_key
from app.constants import RedisKeyPrefix
from app.models.payloads import DLQActionData, DLQListData
from app.models.response import ApiResponse
from app.services.queue import QueueService

router = APIRouter(prefix="/api/v1/dlq", tags=["Dead-Letter Queue"])

@router.get("", response_model=ApiResponse[DLQListData])
async def list_dlq(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    _: str = Depends(verify_api_key),
    queue: QueueService = Depends(get_queue_service),
):
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    raw_list = await queue.redis.lrange(dlq_key, 0, 100)
    entries: list[dict[str, Any]] = []
    for item in raw_list:
        try:
            entries.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            entries.append({"raw": str(item), "parse_error": True})
    return ApiResponse.ok(DLQListData(items=entries, count=len(entries)))

@router.get("/{dlq_id}", response_model=ApiResponse[dict[str, Any]])
async def get_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    _: str = Depends(verify_api_key),
    queue: QueueService = Depends(get_queue_service),
):
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)
    for raw in raw_list:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("dlq_id") == dlq_id:
                return ApiResponse.ok(parsed)
        except (json.JSONDecodeError, TypeError):
            continue
    raise HTTPException(status_code=404, detail="DLQ entry not found")

@router.post("/{dlq_id}/replay", response_model=ApiResponse[DLQActionData])
async def replay_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    _: str = Depends(verify_api_key),
    queue: QueueService = Depends(get_queue_service),
):
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
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

    raw_str = target_raw.decode("utf-8") if isinstance(target_raw, bytes) else str(target_raw)
    await queue.redis.lrem(dlq_key, 1, raw_str)
    await queue.enqueue_batch(x_tenant_id, [payload_to_replay])
    return ApiResponse.ok(DLQActionData(status="replayed", dlq_id=dlq_id))

@router.delete("/{dlq_id}", response_model=ApiResponse[DLQActionData])
async def discard_dlq_entry(
    dlq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    _: str = Depends(verify_api_key),
    queue: QueueService = Depends(get_queue_service),
):
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    raw_list = await queue.redis.lrange(dlq_key, 0, 500)

    for raw in raw_list:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("dlq_id") == dlq_id:
                raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                await queue.redis.lrem(dlq_key, 1, raw_str)
                return ApiResponse.ok(DLQActionData(status="discarded", dlq_id=dlq_id))
        except (json.JSONDecodeError, TypeError):
            continue

    raise HTTPException(status_code=404, detail="DLQ entry not found")
