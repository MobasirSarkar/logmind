from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from correlation.log_store import LogStore


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
        log_store: LogStore | None = None,
        es_client: Any = None,
        min_error_count: int = 10,
        surge_multiplier: float = 3.0,
        absolute_threshold: float = 0.05,
    ):
        if log_store is not None:
            self.log_store = log_store
        elif es_client is not None:
            from correlation.log_store import ESLogStore

            self.log_store = ESLogStore(es_client)
        else:
            raise ValueError("Either log_store or es_client must be provided")
        self.min_error_count = min_error_count
        self.surge_multiplier = surge_multiplier
        self.absolute_threshold = absolute_threshold

    async def evaluate_service(
        self,
        tenant_id: str,
        service: str,
        now: datetime | None = None,
        lookback_seconds: int = 60,
        min_error_count: int | None = None,
    ) -> list[SpikeAlert]:
        t = now or datetime.now(UTC)
        current_start = t - timedelta(seconds=lookback_seconds)
        baseline_start = current_start - timedelta(minutes=10)
        baseline_end = current_start
        curr_err, curr_total = await self.log_store.get_service_error_rate(
            tenant_id, service, current_start, t
        )
        threshold = (
            min_error_count if min_error_count is not None else self.min_error_count
        )
        if curr_err < threshold:
            return []

        curr_rate = curr_err / curr_total

        base_err, base_total = await self.log_store.get_service_error_rate(
            tenant_id, service, baseline_start, baseline_end
        )
        base_rate = base_err / base_total

        is_surge = (
            base_rate > 0 and curr_rate >= self.surge_multiplier * base_rate
        ) or (base_rate == 0 and curr_rate >= self.absolute_threshold)
        if not is_surge:
            return []

        return [
            SpikeAlert(
                tenant_id=tenant_id,
                service=service,
                error_count=curr_err,
                total_requests=curr_total,
                error_rate=curr_rate,
                baseline_rate=base_rate,
            )
        ]
