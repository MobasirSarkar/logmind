# tests/unit/test_queue.py
from unittest.mock import AsyncMock

import pytest

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

@pytest.mark.asyncio
async def test_dlq_operations():
    from app.models.log import DLQEntry, ErrorStage
    mock_redis = AsyncMock()
    queue = QueueService(redis_client=mock_redis)

    entry = DLQEntry(
        dlq_id="dlq-test-1",
        tenant_id="t-1",
        retry_count=3,
        error_stage=ErrorStage.VALIDATION,
        last_error="ValidationError",
        raw_payload={"msg": "bad"},
    )
    # 1. Push DLQ
    count = await queue.push_dlq("t-1", [entry])
    assert count == 1
    mock_redis.lpush.assert_called_once()

    # 2. List DLQ
    mock_redis.lrange.return_value = ['{"dlq_id": "dlq-test-1", "last_error": "ValidationError"}']
    items = await queue.list_dlq("t-1", limit=10)
    assert len(items) == 1
    assert items[0]["dlq_id"] == "dlq-test-1"

    # 3. Get DLQ
    got = await queue.get_dlq("t-1", "dlq-test-1")
    assert got is not None
    assert got["dlq_id"] == "dlq-test-1"

    # 4. Discard DLQ
    discarded = await queue.discard_dlq("t-1", "dlq-test-1")
    assert discarded is True
    mock_redis.lrem.assert_called_once()
