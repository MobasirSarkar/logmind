from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.constants import ESIndexPrefix


class SpikeAlert(BaseModel):
    tenant_id: str
    service: str
    error_count: int
    total_requests: int
    error_rate: float
    baseline_rate: float
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SpikeDetector:
    def __init__(
        self,
        es_client: Any,
        min_error_count: int = 10,
        surge_multiplier: float = 3.0,
        absolute_threshold: float = 0.05,
    ):
        self.es = es_client
        self.min_error_count = min_error_count
        self.surge_multiplier = surge_multiplier
        self.absolute_threshold = absolute_threshold

    def _index_name(self, tenant_id: str) -> str:
        return ESIndexPrefix.LOGS.for_tenant(tenant_id)

    async def evaluate_service(
        self, tenant_id: str, service: str, now: datetime | None = None
    ) -> list[SpikeAlert]:
        t = now or datetime.now(UTC)
        current_start = t - timedelta(seconds=60)
        baseline_start = t - timedelta(minutes=10)
        index = self._index_name(tenant_id)

        # 1. Current window error count
        curr_err_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"context.service": service}},
                        {"range": {"timestamp": {"gte": current_start.isoformat(), "lte": t.isoformat()}}},
                        {"terms": {"level": ["ERROR", "FATAL"]}},
                    ]
                }
            }
        }
        res = await self.es.count(index=index, body=curr_err_body)
        curr_err_count = int(res.get("count", 0))

        if curr_err_count < self.min_error_count:
            return []

        # 2. Current window total count
        curr_total_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"context.service": service}},
                        {"range": {"timestamp": {"gte": current_start.isoformat(), "lte": t.isoformat()}}},
                    ]
                }
            }
        }
        res_total = await self.es.count(index=index, body=curr_total_body)
        curr_total_count = max(int(res_total.get("count", 0)), curr_err_count, 1)
        curr_rate = curr_err_count / curr_total_count

        # 3. Baseline window error count
        base_err_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"context.service": service}},
                        {"range": {"gte": baseline_start.isoformat(), "lt": current_start.isoformat()}},
                        {"terms": {"level": ["ERROR", "FATAL"]}},
                    ]
                }
            }
        }
        res_base_err = await self.es.count(index=index, body=base_err_body)
        base_err_count = int(res_base_err.get("count", 0))

        # 4. Baseline window total count
        base_total_body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"context.service": service}},
                        {"range": {"gte": baseline_start.isoformat(), "lt": current_start.isoformat()}},
                    ]
                }
            }
        }
        res_base_total = await self.es.count(index=index, body=base_total_body)
        base_total_count = max(int(res_base_total.get("count", 0)), 1)
        base_rate = base_err_count / base_total_count

        # 5. Evaluate surge criteria
        is_surge = False
        if base_rate > 0:
            if curr_rate >= self.surge_multiplier * base_rate:
                is_surge = True
        elif curr_rate >= self.absolute_threshold:
            is_surge = True

        if is_surge:
            alert = SpikeAlert(
                tenant_id=tenant_id,
                service=service,
                error_count=curr_err_count,
                total_requests=curr_total_count,
                error_rate=curr_rate,
                baseline_rate=base_rate,
                detected_at=t,
            )
            return [alert]

        return []
