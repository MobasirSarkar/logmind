from typing import Annotated

import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.queue import QueueService

_queue_service: QueueService | None = None
_es_service: ElasticsearchService | None = None
_embedding_service: EmbeddingService | None = None

# Module-level header aliases
ApiKeyHeader = Annotated[str, Header(alias="X-API-Key")]
TenantIdHeader = Annotated[str, Header(alias="X-Tenant-ID")]

def verify_api_key(x_api_key: ApiKeyHeader) -> str:
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

def get_queue_service() -> QueueService:
    global _queue_service
    if _queue_service is None:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _queue_service = QueueService(client, max_depth=settings.QUEUE_MAX_DEPTH)
    return _queue_service

def get_es_service() -> ElasticsearchService:
    global _es_service
    if _es_service is None:
        client = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
        _es_service = ElasticsearchService(client)
    return _es_service

def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(settings.EMBEDDING_MODEL_NAME)
    return _embedding_service


async def close_services() -> None:
    global _queue_service, _es_service, _embedding_service
    if _queue_service is not None:
        await _queue_service.redis.aclose()
        _queue_service = None
    if _es_service is not None:
        await _es_service.es.close()
        _es_service = None
    _embedding_service = None
# Module-level dependency aliases satisfying B008
QueueDep = Annotated[QueueService, Depends(get_queue_service)]
EsDep = Annotated[ElasticsearchService, Depends(get_es_service)]
EmbeddingDep = Annotated[EmbeddingService, Depends(get_embedding_service)]
ApiKeyDep = Annotated[str, Depends(verify_api_key)]
