# tests/unit/test_queue.py
import pytest
from unittest.mock import AsyncMock
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
