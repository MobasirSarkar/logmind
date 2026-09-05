import json
from typing import cast

import redis.asyncio as aioredis

from app.constants import RedisKeyPrefix
from app.models.log import RawLogPayload


class QueueService:
    def __init__(self, redis_client: aioredis.Redis, max_depth: int = 50000):
        self.redis: aioredis.Redis = redis_client
        self.max_depth: int = max_depth

    def _queue_key(self, tenant_id: str) -> str:
        return RedisKeyPrefix.QUEUE.for_tenant(tenant_id)

    async def get_queue_depth(self, tenant_id: str) -> int:
        return await self.redis.llen(self._queue_key(tenant_id))

    async def is_queue_saturated(self, tenant_id: str) -> bool:
        depth = await self.get_queue_depth(tenant_id)
        return depth >= self.max_depth

    async def enqueue_batch(self, tenant_id: str, logs: list[RawLogPayload]) -> int:
        key = self._queue_key(tenant_id)
        serialized = [json.dumps(log) for log in logs]
        _ = await self.redis.lpush(key, *serialized)
        return len(logs)

    async def dequeue_batch(self, tenant_id: str, batch_size: int = 500) -> list[RawLogPayload]:
        key = self._queue_key(tenant_id)
        items: list[RawLogPayload] = []
        for _ in range(batch_size):
            raw = await self.redis.rpop(key)
            if raw is None:
                break
            if isinstance(raw, (str, bytes, bytearray)):
                items.append(cast(RawLogPayload, json.loads(raw)))
        return items
