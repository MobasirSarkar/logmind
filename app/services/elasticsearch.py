from typing import Any, Dict, List
from elasticsearch import AsyncElasticsearch, helpers
from app.models.log import LogRecord

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.es = es_client

    def _index_name(self, tenant_id: str) -> str:
        return f"logmind-logs-{tenant_id}"

    async def bulk_index(self, records: List[LogRecord]) -> int:
        if not records:
            return 0
        actions: List[Dict[str, Any]] = []
        for rec in records:
            action = {
                "_index": self._index_name(rec.context.tenant_id),
                "_id": rec.fingerprint.content_hash if rec.fingerprint else rec.id,
                "_source": rec.model_dump(mode="json"),
            }
            actions.append(action)
        success_count, _ = await helpers.async_bulk(self.es, actions)
        return success_count
