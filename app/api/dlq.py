import json
from typing import cast

from fastapi import APIRouter, HTTPException

from app.api.deps import ApiKeyDep, QueueDep, TenantIdHeader
from app.constants import RedisKeyPrefix
from app.models.log import RawLogPayload
from app.models.payloads import DLQActionData, DLQItem, DLQListData
from app.models.response import ApiResponse
from app.services.queue import QueueService

router = APIRouter(prefix="/api/v1/dlq", tags=["Dead-Letter Queue"])

def _to_str(raw: str | bytes | bytearray) -> str:
    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)


def _parse_dlq_item(raw: str | bytes | bytearray) -> DLQItem | None:
    try:
        data = json.loads(raw)
        return cast(DLQItem, data) if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


async def _find_dlq_entry(
    queue: QueueService,
    tenant_id: str,
    dlq_id: str,
    limit: int = 500,
) -> tuple[str, DLQItem] | None:
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(tenant_id)
    raw_list = await queue.redis.lrange(dlq_key, 0, limit)
    for raw in raw_list:
        parsed = _parse_dlq_item(raw)
        if parsed and parsed.get("dlq_id") == dlq_id:
            return _to_str(raw), parsed
    return None


@router.get("")
async def list_dlq(
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQListData]:
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    raw_list = await queue.redis.lrange(dlq_key, 0, 100)
    entries: list[DLQItem] = [
        _parse_dlq_item(item) or {"raw": _to_str(item), "parse_error": True}
        for item in raw_list
    ]
    return ApiResponse[DLQListData].ok(DLQListData(items=entries, count=len(entries)))

@router.get("/{dlq_id}")
async def get_dlq_entry(
    dlq_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQItem]:
    found = await _find_dlq_entry(queue, x_tenant_id, dlq_id)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    _, entry = found
    return ApiResponse[DLQItem].ok(entry)

@router.post("/{dlq_id}/replay")
async def replay_dlq_entry(
    dlq_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQActionData]:
    found = await _find_dlq_entry(queue, x_tenant_id, dlq_id)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    raw_str, entry = found
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    _ = await queue.redis.lrem(dlq_key, 1, raw_str)
    raw_payload = entry.get("raw_payload", entry)
    payload_to_replay = cast(RawLogPayload, raw_payload if isinstance(raw_payload, dict) else entry)
    _ = await queue.enqueue_batch(x_tenant_id, [payload_to_replay])
    return ApiResponse[DLQActionData].ok(
        DLQActionData(status="replayed", dlq_id=dlq_id)
    )

@router.delete("/{dlq_id}")
async def discard_dlq_entry(
    dlq_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQActionData]:
    found = await _find_dlq_entry(queue, x_tenant_id, dlq_id)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    raw_str, _ = found
    dlq_key = RedisKeyPrefix.DLQ.for_tenant(x_tenant_id)
    _ = await queue.redis.lrem(dlq_key, 1, raw_str)
    return ApiResponse[DLQActionData].ok(
        DLQActionData(status="discarded", dlq_id=dlq_id)
    )
