from typing import Any

from pydantic import BaseModel


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
    hits: list[dict[str, Any]]
