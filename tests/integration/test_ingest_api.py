# tests/integration/test_ingest_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from app.main import create_app

@pytest.mark.asyncio
async def test_ingest_logs_success_202():
    app = create_app()
    with patch("app.api.ingest.get_queue_service") as mock_get_qs:
        mock_qs = AsyncMock()
        mock_qs.is_queue_saturated.return_value = False
        mock_qs.enqueue_batch.return_value = 2
        mock_get_qs.return_value = mock_qs

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/logs/ingest",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-test"},
                json={"logs": [{"level": "INFO", "message": "hello"}, {"level": "ERROR", "message": "crash"}]}
            )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "queued"
        assert data["received_count"] == 2
        assert "batch_id" in data

@pytest.mark.asyncio
async def test_ingest_logs_queue_saturated_429():
    app = create_app()
    with patch("app.api.ingest.get_queue_service") as mock_get_qs:
        mock_qs = AsyncMock()
        mock_qs.is_queue_saturated.return_value = True
        mock_get_qs.return_value = mock_qs

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/logs/ingest",
                headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-test"},
                json={"logs": [{"message": "test"}]}
            )
        assert res.status_code == 429
        assert res.headers["Retry-After"] == "5"
