from typing import Any, cast
from pydantic import BaseModel, ConfigDict, Field


class TotalHits(BaseModel):
    value: int = 0
    relation: str = "eq"

class SearchHit[T](BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    index: str = Field(alias="_index")
    id: str = Field(alias="_id")
    score: float | None = Field(default=None, alias="_score")
    source: T = Field(alias="_source")

class HitsMetadata[T](BaseModel):
    total: TotalHits = Field(default_factory=TotalHits)
    max_score: float | None = None
    hits: list[SearchHit[T]] = Field(default_factory=list)

class ESSearchResult[T](BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    took: int | None = None
    timed_out: bool = False
    hits: HitsMetadata[T] = Field(default_factory=lambda: cast(Any, HitsMetadata()))
