from typing import Any
from elasticsearch import AsyncElasticsearch, helpers

from app.constants import ESIndexPrefix
from app.models.log import LogRecord
from app.models.search import ESSearchResult

def build_exact_query(query: str, limit: int) -> dict[str, Any]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message", "error.error_message", "error.error_type"],
            }
        },
        "size": limit,
    }

def build_semantic_query(query_vector: list[float], limit: int) -> dict[str, Any]:
    return {
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
        },
        "size": limit,
    }

def build_hybrid_query(query: str, query_vector: list[float], limit: int) -> dict[str, Any]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message", "error.error_message", "error.error_type"],
            }
        },
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
        },
        "rank": {"rrf": {"window_size": 50, "rank_constant": 60}},
        "size": limit,
    }

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.es = es_client

    def _index_name(self, tenant_id: str) -> str:
        return ESIndexPrefix.LOGS.for_tenant(tenant_id)

    async def bulk_index(self, records: list[LogRecord]) -> int:
        if not records:
            return 0
        actions: list[dict[str, Any]] = []
        for rec in records:
            action = {
                "_index": self._index_name(rec.context.tenant_id),
                "_id": rec.fingerprint.content_hash if rec.fingerprint else rec.id,
                "_source": rec.model_dump(mode="json"),
            }
            actions.append(action)
        success_count, _ = await helpers.async_bulk(self.es, actions)
        return success_count

    async def search(
        self,
        tenant_id: str,
        query: str,
        mode: str = "hybrid",
        query_vector: list[float] | None = None,
        limit: int = 20,
    ) -> ESSearchResult[dict[str, Any]]:
        index = self._index_name(tenant_id)

        if mode == "exact":
            body = build_exact_query(query, limit)
        elif mode == "semantic" and query_vector is not None:
            body = build_semantic_query(query_vector, limit)
        else:
            body = build_hybrid_query(query, query_vector or ([0.0] * 384), limit)

        res = await self.es.search(index=index, body=body)
        return ESSearchResult[dict[str, Any]].model_validate(res.body)
