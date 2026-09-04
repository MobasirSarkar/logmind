import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_queue_service, verify_api_key
from app.models.payloads import LogBatchResponseData
from app.models.response import ApiResponse
from app.services.queue import QueueService

router = APIRouter(prefix="/api/v1/logs", tags=["Ingestion"])

class LogBatchPayload(BaseModel):
    logs: list[dict[str, Any]] = Field(..., min_length=1, max_length=500)

@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED, response_model=ApiResponse[LogBatchResponseData])
async def ingest_logs(
    payload: LogBatchPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    _: str = Depends(verify_api_key),
    queue_service: QueueService = Depends(get_queue_service),
):
    if await queue_service.is_queue_saturated(x_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Queue depth exceeded threshold",
            headers={"Retry-After": "5"}
        )

    batch_id = str(uuid.uuid4())
    await queue_service.enqueue_batch(x_tenant_id, payload.logs)

    return ApiResponse.ok(
        LogBatchResponseData(
            status="queued",
            batch_id=batch_id,
            received_count=len(payload.logs),
            tenant_id=x_tenant_id,
        )
    )
