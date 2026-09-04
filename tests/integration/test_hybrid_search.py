# tests/integration/test_hybrid_search.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from app.api.deps import get_embedding_service, get_es_service
from app.main import create_app

@pytest.mark.asyncio
async def test_search_hybrid_execution():
    app = create_app()
    mock_es = AsyncMock()
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_id": "ch-123",
                    "_source": {
                        "message": "GatewayTimeoutException",
                        "level": "ERROR",
                        "context": {"service": "payment-service"}
                    }
                }
            ]
        }
    }
    mock_embed = MagicMock()
    mock_embed.get_or_compute_embedding.return_value = [0.05] * 384
    app.dependency_overrides[get_es_service] = lambda: mock_es
    app.dependency_overrides[get_embedding_service] = lambda: mock_embed

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/logs/search",
            headers={"X-Tenant-ID": "tenant-test", "X-API-Key": "lmd_dev_key"},
            json={"query": "payment timeout", "mode": "hybrid", "limit": 10}
        )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total"] == 1
    assert data["hits"][0]["_source"]["context"]["service"] == "payment-service"
