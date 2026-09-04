from typing import Any, Optional, cast
from elasticsearch import AsyncElasticsearch, helpers
from app.models.log import LogRecord

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.es = es_client

    def _index_name(self, tenant_id: str) -> str:
        return f"logmind-logs-{tenant_id}"

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
        query_vector: Optional[list[float]] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        index = self._index_name(tenant_id)
        
        if mode == "exact":
            body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["message", "error.error_message", "error.error_type"]
                    }
                },
                "size": limit
            }
            res = await self.es.search(index=index, body=body)
            return cast(dict[str, Any], res.body)

        if mode == "semantic" and query_vector:
            body = {
                "knn": {
                    "field": "fingerprint.embedding",
                    "query_vector": query_vector,
                    "k": limit,
                    "num_candidates": limit * 5
                },
                "size": limit
            }
            res = await self.es.search(index=index, body=body)
            return cast(dict[str, Any], res.body)

        # Hybrid Search (RRF)
        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["message", "error.error_message", "error.error_type"]
                }
            },
            "knn": {
                "field": "fingerprint.embedding",
                "query_vector": query_vector or ([0.0] * 384),
                "k": limit,
                "num_candidates": limit * 5
            },
            "rank": {"rrf": {"window_size": 50, "rank_constant": 60}},
            "size": limit
        }
        res = await self.es.search(index=index, body=body)
        return cast(dict[str, Any], res.body)
