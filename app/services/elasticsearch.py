from typing import cast

from elasticsearch import AsyncElasticsearch, NotFoundError, helpers

from app.constants import ESIndexPrefix
from app.models.log import LogRecord
from app.models.search import ESSearchResponse, ESSearchResult
from app.queries.elasticsearch import (
    build_exact_query,
    build_hybrid_query,
    build_semantic_query,
)


class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.es: AsyncElasticsearch = es_client

    def _index_name(self, tenant_id: str) -> str:
        return ESIndexPrefix.LOGS.for_tenant(tenant_id)

    async def ensure_index_template(self) -> None:
        template = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "timestamp": {"type": "date"},
                    "level": {"type": "keyword"},
                    "message": {"type": "text"},
                    "context": {
                        "properties": {
                            "tenant_id": {"type": "keyword"},
                            "service": {"type": "keyword"},
                            "environment": {"type": "keyword"},
                        }
                    },
                    "fingerprint": {
                        "properties": {
                            "content_hash": {"type": "keyword"},
                            "signature_hash": {"type": "keyword"},
                            "hash_type": {"type": "keyword"},
                            "embedding": {
                                "type": "dense_vector",
                                "dims": 384,
                                "index": True,
                                "similarity": "cosine",
                            },
                        }
                    },
                    "error": {
                        "properties": {
                            "error_type": {"type": "keyword"},
                            "error_message": {"type": "text"},
                            "error_signature": {"type": "text"},
                        }
                    },
                }
            }
        }
        _ = await self.es.indices.put_index_template(
            name="logmind-logs-template",
            index_patterns=["logmind-logs-*"],
            template=template,
        )


    async def bulk_index(self, records: list[LogRecord]) -> int:
        if not records:
            return 0
        actions = [
            {
                "_index": self._index_name(rec.context.tenant_id),
                "_id": rec.fingerprint.content_hash if rec.fingerprint else rec.id,
                "_source": rec.model_dump(mode="json"),
            }
            for rec in records
        ]
        success_count, _ = await helpers.async_bulk(self.es, actions, refresh=True)
        return success_count

    async def search(
        self,
        tenant_id: str,
        query: str,
        mode: str = "hybrid",
        query_vector: list[float] | None = None,
        limit: int = 20,
    ) -> ESSearchResult:
        index = self._index_name(tenant_id)

        if mode == "exact" or query_vector is None:
            body = build_exact_query(query, limit)
        elif mode == "semantic":
            body = build_semantic_query(query_vector, limit)
        else:
            body = build_hybrid_query(query, query_vector, limit)

        try:
            res = await self.es.search(index=index, body=body)
            return ESSearchResult.model_validate(cast(ESSearchResponse, res.body))
        except NotFoundError:
            return ESSearchResult.model_validate(
                {"hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}
            )
