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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Queue depth exceeded threshold",
            headers={"Retry-After": "5"}
        )

    batch_id = str(uuid.uuid4())
    await queue_service.enqueue_batch(x_tenant_id, payload.logs)

    return {
        "status": "queued",
        "batch_id": batch_id,
        "received_count": len(payload.logs),
        "tenant_id": x_tenant_id,
    }
