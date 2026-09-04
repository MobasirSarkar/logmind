
import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch
from fastapi import Header, HTTPException

from app.config import settings
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.queue import QueueService

_queue_service: QueueService | None = None
_es_service: ElasticsearchService | None = None
_embedding_service: EmbeddingService | None = None

def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
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
