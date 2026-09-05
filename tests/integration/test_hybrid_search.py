# tests/integration/test_hybrid_search.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import NotFoundError
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_embedding_service, get_es_service
from app.main import create_app
from app.models.search import ESSearchResult
from app.services.elasticsearch import ElasticsearchService


@pytest.mark.asyncio
async def test_search_hybrid_execution():
    app = create_app()
    mock_es = AsyncMock()
    mock_es.search.return_value = ESSearchResult.model_validate({
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {
                    "_index": "logmind-logs-tenant-test",
                    "_id": "ch-123",
                    "_source": {
                        "message": "GatewayTimeoutException",
                        "level": "ERROR",
                        "context": {"service": "payment-service"}
                    }
                }
            ]
        }
    })
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


@pytest.mark.asyncio
async def test_search_missing_index_returns_empty_results():
    mock_client = AsyncMock()
    meta = ApiResponseMeta(404, "HTTP/1.1", HttpHeaders(), 0.0, NodeConfig("http", "localhost", 9200))
    mock_client.search.side_effect = NotFoundError("no such index [logmind-logs-acme]", meta, {})
    svc = ElasticsearchService(mock_client)
    res = await svc.search(tenant_id="acme", query="anything")
    assert res.hits.total.value == 0
    assert res.hits.hits == []
