from typing import Any
from pydantic import BaseModel
from app.models.search import SearchHit

class DLQActionData(BaseModel):
    status: str
    dlq_id: str

class DLQListData(BaseModel):
    items: list[dict[str, Any]]
    count: int

class LogBatchResponseData(BaseModel):
    status: str = "queued"
    batch_id: str
    received_count: int
    tenant_id: str

class SearchResponseData(BaseModel):
    total: int
    hits: list[SearchHit[dict[str, Any]]]
