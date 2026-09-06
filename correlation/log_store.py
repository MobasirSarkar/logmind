from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.constants import ESIndexPrefix
from app.models.log import RawLogPayload


@runtime_checkable
class LogStore(Protocol):
    """Seam between CorrelationEngine and log storage."""

    async def get_active_services(
        self, tenant_id: str, start: datetime, end: datetime
    ) -> list[str]: ...

    async def get_error_logs(
        self,
        tenant_id: str,
        services: list[str],
        start: datetime,
        end: datetime,
        limit: int = 500,
    ) -> list[RawLogPayload]: ...

    async def get_service_error_rate(
        self,
        tenant_id: str,
        service: str,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[int, int]: ...

    """Returns (error_count, total_count) for the window."""


def _extract_es_dict(res: Any) -> dict[str, Any]:
    if hasattr(res, "body") and isinstance(res.body, dict):
        return res.body
    if isinstance(res, dict):
        return res
    return {}


class ESLogStore:
    """Adapter: satisfies LogStore using Elasticsearch."""

    def __init__(self, es_client: Any) -> None:
        self._es = es_client

    def _index(self, tenant_id: str) -> str:
        return ESIndexPrefix.LOGS.for_tenant(tenant_id)

    async def get_active_services(
        self, tenant_id: str, start: datetime, end: datetime
    ) -> list[str]:
        body = {
            "query": {
                "range": {
                    "timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}
                }
            },
            "aggs": {"services": {"terms": {"field": "context.service", "size": 50}}},
            "size": 0,
        }
        try:
            res = await self._es.search(index=self._index(tenant_id), body=body)
        except Exception:  # noqa: BLE001
            return []
        data = _extract_es_dict(res)
        buckets = data.get("aggregations", {}).get("services", {}).get("buckets", [])
        return [str(b["key"]) for b in buckets if isinstance(b, dict) and "key" in b]

    async def get_error_logs(
        self,
        tenant_id: str,
        services: list[str],
        start: datetime,
        end: datetime,
        limit: int = 500,
    ) -> list[RawLogPayload]:
        from typing import cast

        body = {
            "query": {
                "bool": {
                    "must": [
                        {"terms": {"context.service": services}},
                        {"terms": {"level": ["ERROR", "FATAL"]}},
                        {
                            "range": {
                                "timestamp": {
                                    "gte": start.isoformat(),
                                    "lte": end.isoformat(),
                                }
                            }
                        },
                    ]
                }
            },
            "size": limit,
        }
        try:
            res = await self._es.search(index=self._index(tenant_id), body=body)
        except Exception:  # noqa: BLE001
            return []
        data = _extract_es_dict(res)
        hits = data.get("hits", {}).get("hits", [])
        return [
            cast(RawLogPayload, h["_source"])
            for h in hits
            if isinstance(h, dict) and isinstance(h.get("_source"), dict)
        ]

    async def get_service_error_rate(
        self,
        tenant_id: str,
        service: str,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[int, int]:
        index = self._index(tenant_id)
        time_range = {
            "range": {
                "timestamp": {
                    "gte": window_start.isoformat(),
                    "lte": window_end.isoformat(),
                }
            }
        }
        service_term = {"term": {"context.service": service}}
        err_body = {
            "query": {
                "bool": {
                    "must": [
                        service_term,
                        time_range,
                        {"terms": {"level": ["ERROR", "FATAL"]}},
                    ]
                }
            }
        }
        total_body = {"query": {"bool": {"must": [service_term, time_range]}}}
        try:
            r_err = await self._es.count(index=index, body=err_body)
            r_total = await self._es.count(index=index, body=total_body)
        except Exception:  # noqa: BLE001
            return 0, 1
        d_err = _extract_es_dict(r_err)
        d_tot = _extract_es_dict(r_total)
        return int(d_err.get("count", 0)), max(int(d_tot.get("count", 0)), 1)
