import logging

import httpx

from app.config import settings
from app.models.log import RawLogPayload

logger = logging.getLogger("uvicorn.error")


class AsyncLogShipper:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or settings.API_KEY
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def ship_batch(self, tenant_id: str, logs: list[RawLogPayload]) -> tuple[bool, int]:
        if not logs:
            return True, 0
        client = await self._get_client()
        url = f"{self.base_url}/api/v1/logs/ingest"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Tenant-ID": tenant_id,
        }
        try:
            res = await client.post(url, headers=headers, json={"logs": logs})
            if res.status_code in (200, 202):
                return True, len(logs)
            logger.warning("Shipper failed to ingest batch (%d): %s", res.status_code, res.text)
            return False, 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Shipper network exception: %s", exc)
            return False, 0

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
