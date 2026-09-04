from enum import Enum
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ApiKeyDep, EmbeddingDep, EsDep, TenantIdHeader
from app.models.payloads import SearchResponseData
from app.models.response import ApiResponse
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

@router.post("/search", response_model=ApiResponse[SearchResponseData])
async def search_logs(
    req: SearchRequest,
    x_tenant_id: TenantIdHeader,
    _: ApiKeyDep,
    es: EsDep,
    embed: EmbeddingDep,
):
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
    return ApiResponse.ok(
        SearchResponseData(
            total=res.get("hits", {}).get("total", {}).get("value", 0),
            hits=res.get("hits", {}).get("hits", []),
        )
    )
