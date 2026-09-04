from enum import Enum
from typing import Any, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from app.config import settings
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import generate_signature_hash

router = APIRouter(prefix="/api/v1/logs", tags=["Search"])

class SearchMode(str, Enum):
    EXACT = "exact"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"

class SearchRequest(BaseModel):
    query: str
    mode: SearchMode = SearchMode.HYBRID
    limit: int = Field(default=20, ge=1, le=100)

_es_service = None
_embedding_service = None

def get_es_service() -> ElasticsearchService:
    global _es_service
    if _es_service is None:
        from elasticsearch import AsyncElasticsearch
        client = AsyncElasticsearch(settings.ELASTICSEARCH_URL)
        _es_service = ElasticsearchService(client)
    return _es_service

def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(settings.EMBEDDING_MODEL_NAME)
    return _embedding_service

@router.post("/search")
async def search_logs(
    req: SearchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    es = get_es_service()
    embed = get_embedding_service()

    vector = None
    if req.mode in (SearchMode.SEMANTIC, SearchMode.HYBRID):
        s_hash = generate_signature_hash(req.query)
        vector = embed.get_or_compute_embedding(s_hash, req.query)

    res = await es.search(
        tenant_id=x_tenant_id,
        query=req.query,
        mode=req.mode.value,
        query_vector=vector,
        limit=req.limit,
    )
    return {
        "total": res.get("hits", {}).get("total", {}).get("value", 0),
        "hits": res.get("hits", {}).get("hits", []),
    }
