import json
from typing import cast

import redis.asyncio as aioredis

from app.constants import RedisKeyPrefix
from app.models.log import DLQEntry, RawLogPayload
from app.models.payloads import DLQItem


class LogQueue:
    def __init__(self, redis_client: aioredis.Redis, max_depth: int = 50000):
        self.redis: aioredis.Redis = redis_client
        self.max_depth: int = max_depth
    def _queue_key(self, tenant_id: str) -> str:
        return RedisKeyPrefix.QUEUE.for_tenant(tenant_id)

    def _dlq_key(self, tenant_id: str) -> str:
        return RedisKeyPrefix.DLQ.for_tenant(tenant_id)

    def _to_str(self, raw: str | bytes | bytearray) -> str:
        return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)

    def _parse_dlq_item(self, raw: str | bytes | bytearray) -> DLQItem | None:
        try:
            data = json.loads(raw)
            return cast(DLQItem, data) if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None
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

    async def push_dlq(self, tenant_id: str, entries: list[DLQEntry]) -> int:
        if not entries:
            return 0
        key = self._dlq_key(tenant_id)
        serialized = [json.dumps(d.model_dump(mode="json")) for d in entries]
        _ = await self.redis.lpush(key, *serialized)
        return len(entries)

    async def list_dlq(self, tenant_id: str, limit: int = 100) -> list[DLQItem]:
        key = self._dlq_key(tenant_id)
        raw_list = await self.redis.lrange(key, 0, limit)
        return [
            self._parse_dlq_item(item) or {"raw": self._to_str(item), "parse_error": True}
            for item in raw_list
        ]

    async def _find_dlq_entry(
        self, tenant_id: str, dlq_id: str, limit: int = 500
    ) -> tuple[str, DLQItem] | None:
        key = self._dlq_key(tenant_id)
        raw_list = await self.redis.lrange(key, 0, limit)
        for raw in raw_list:
            parsed = self._parse_dlq_item(raw)
            if parsed and parsed.get("dlq_id") == dlq_id:
                return self._to_str(raw), parsed
        return None

    async def get_dlq(self, tenant_id: str, dlq_id: str) -> DLQItem | None:
        found = await self._find_dlq_entry(tenant_id, dlq_id)
        return found[1] if found else None

    async def replay_dlq(self, tenant_id: str, dlq_id: str) -> bool:
        found = await self._find_dlq_entry(tenant_id, dlq_id)
        if not found:
            return False
        raw_str, entry = found
        key = self._dlq_key(tenant_id)
        _ = await self.redis.lrem(key, 1, raw_str)
        raw_payload = entry.get("raw_payload", entry)
        payload_to_replay = cast(
            RawLogPayload, raw_payload if isinstance(raw_payload, dict) else entry
        )
        _ = await self.enqueue_batch(tenant_id, [payload_to_replay])
        return True

    async def discard_dlq(self, tenant_id: str, dlq_id: str) -> bool:
        found = await self._find_dlq_entry(tenant_id, dlq_id)
        if not found:
            return False
        raw_str, _ = found
        key = self._dlq_key(tenant_id)
        _ = await self.redis.lrem(key, 1, raw_str)
        return True


QueueService = LogQueue
