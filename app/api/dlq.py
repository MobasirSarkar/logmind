from fastapi import APIRouter, HTTPException

from app.api.deps import ApiKeyDep, QueueDep, TenantIdHeader
from app.models.payloads import DLQActionData, DLQItem, DLQListData
from app.models.response import ApiResponse

router = APIRouter(prefix="/api/v1/dlq", tags=["Dead-Letter Queue"])


@router.get("")
async def list_dlq(
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQListData]:
    items = await queue.list_dlq(x_tenant_id, limit=100)
    return ApiResponse[DLQListData].ok(DLQListData(items=items, count=len(items)))


@router.get("/{dlq_id}")
async def get_dlq_entry(
    dlq_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQItem]:
    entry = await queue.get_dlq(x_tenant_id, dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return ApiResponse[DLQItem].ok(entry)


@router.post("/{dlq_id}/replay")
async def replay_dlq_entry(
    dlq_id: str,
    x_tenant_id: TenantIdHeader,
    _api_key: ApiKeyDep,
    queue: QueueDep,
) -> ApiResponse[DLQActionData]:
    success = await queue.replay_dlq(x_tenant_id, dlq_id)
    if not success:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
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
    success = await queue.discard_dlq(x_tenant_id, dlq_id)
    if not success:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return ApiResponse[DLQActionData].ok(
        DLQActionData(status="discarded", dlq_id=dlq_id)
    )
