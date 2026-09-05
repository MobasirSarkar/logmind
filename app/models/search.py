from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class TotalHits(BaseModel):
    value: int = 0
    relation: str = "eq"


class SearchHit(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    index: str = Field(alias="_index")
    id: str = Field(alias="_id")
    score: float | None = Field(default=None, alias="_score")
    source: dict[str, object] = Field(default_factory=dict, alias="_source")


class HitsMetadata(BaseModel):
    total: TotalHits = Field(default_factory=TotalHits)
    max_score: float | None = None
    hits: list[SearchHit] = Field(default_factory=list)


class ESSearchResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    took: int | None = None
    timed_out: bool = False
    hits: HitsMetadata = Field(default_factory=HitsMetadata)


type ESSearchResponse = dict[str, object]
