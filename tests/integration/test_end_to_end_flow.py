# tests/integration/test_end_to_end_flow.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from app.api.deps import get_embedding_service, get_es_service, get_queue_service
from app.main import create_app

@pytest.mark.asyncio
async def test_full_pipeline_ingest_to_search_and_dlq():
    app = create_app()
    mock_qs = AsyncMock()
    mock_qs.is_queue_saturated.return_value = False
    mock_qs.enqueue_batch.return_value = 1
    mock_es = AsyncMock()
    mock_es.search.return_value = {
        "hits": {"total": {"value": 1}, "hits": [{"_id": "1", "_source": {"message": "Success"}}]}
    }
    mock_embed = MagicMock()
    mock_embed.get_or_compute_embedding.return_value = [0.1] * 384
    app.dependency_overrides[get_queue_service] = lambda: mock_qs
    app.dependency_overrides[get_es_service] = lambda: mock_es
    app.dependency_overrides[get_embedding_service] = lambda: mock_embed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Ingest
        ingest_res = await ac.post(
            "/api/v1/logs/ingest",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-e2e"},
            json={"logs": [{"level": "ERROR", "message": "Critical failure"}]}
        )
        assert ingest_res.status_code == 202
        assert ingest_res.json()["success"] is True
        assert ingest_res.json()["data"]["status"] == "queued"
        # 2. Search
        search_res = await ac.post(
            "/api/v1/logs/search",
            headers={"X-API-Key": "lmd_dev_key", "X-Tenant-ID": "tenant-e2e"},
            json={"query": "Critical failure", "mode": "hybrid"}
        )
        assert search_res.status_code == 200
        assert search_res.json()["success"] is True
        assert search_res.json()["data"]["total"] == 1
