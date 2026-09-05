from pydantic import BaseModel

from app.models.search import SearchHit

type DLQItem = dict[str, object]

class DLQActionData(BaseModel):
    status: str
    dlq_id: str

class DLQListData(BaseModel):
    items: list[DLQItem]
    count: int

class LogBatchResponseData(BaseModel):
    status: str = "queued"
    batch_id: str
    received_count: int
    tenant_id: str

class SearchResponseData(BaseModel):
    total: int
    hits: list[SearchHit]
