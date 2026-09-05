# tests/integration/test_dlq_api.py
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_queue_service
from app.main import create_app


@pytest.mark.asyncio
async def test_dlq_list_and_replay():
    app = create_app()
    mock_qs = AsyncMock()
    fake_entry = '{"dlq_id": "dlq-123", "tenant_id": "t-1", "retry_count": 3, "error_stage": "VALIDATION", "last_error": "ValidationError", "raw_payload": {"msg": "bad"}}'
    mock_qs.redis.lrange.return_value = [fake_entry]
    mock_qs.redis.lrem.return_value = 1
    mock_qs.redis.lpush.return_value = 1
    app.dependency_overrides[get_queue_service] = lambda: mock_qs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. List DLQ
        list_res = await ac.get("/api/v1/dlq", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
        assert list_res.status_code == 200
        list_body = list_res.json()
        assert list_body["success"] is True
        items = list_body["data"]["items"]
        assert len(items) == 1
        assert items[0]["dlq_id"] == "dlq-123"

        # 2. Replay DLQ
        replay_res = await ac.post("/api/v1/dlq/dlq-123/replay", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
        assert replay_res.status_code == 200
        replay_body = replay_res.json()
        assert replay_body["success"] is True
        assert replay_body["data"]["status"] == "replayed"

        # 3. Get single DLQ entry
        get_res = await ac.get("/api/v1/dlq/dlq-123", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
        assert get_res.status_code == 200
        get_body = get_res.json()
        assert get_body["success"] is True
        assert get_body["data"]["dlq_id"] == "dlq-123"

        # 4. Discard DLQ entry
        del_res = await ac.delete("/api/v1/dlq/dlq-123", headers={"X-Tenant-ID": "t-1", "X-API-Key": "lmd_dev_key"})
        assert del_res.status_code == 200
        del_body = del_res.json()
        assert del_body["success"] is True
        assert del_body["data"]["status"] == "discarded"
