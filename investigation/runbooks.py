import asyncio
import hashlib
import logging
import uuid
from typing import Any, Protocol, cast, runtime_checkable

from investigation.models import RunbookItem

logger = logging.getLogger("uvicorn.error")


def _extract_es_dict(res: Any) -> dict[str, Any]:
    if hasattr(res, "body") and isinstance(res.body, dict):
        return res.body
    if isinstance(res, dict):
        return res
    return {}


@runtime_checkable
class RunbookStore(Protocol):
    """Seam for runbook search. Two adapters make this seam real:
    ESRunbookAdapter (production) and an in-memory stub (tests).
    # ponytail: in-memory adapter when first runbook integration test is written
    """

    async def search_runbooks(
        self,
        tenant_id: str,
        query: str,
        service: str | None = None,
        limit: int = 5,
    ) -> list[RunbookItem]: ...


class RunbookService:
    def __init__(self, es_service: Any, embedding_service: Any):
        self.es = es_service
        self.embeddings = embedding_service

    def _index_name(self, tenant_id: str) -> str:
        return f"logmind-runbooks-{tenant_id}"

    async def ensure_runbook_template(self) -> None:
        template = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "service": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": 384,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            }
        }
        try:
            _ = await self.es.indices.put_index_template(
                name="logmind-runbooks-template",
                index_patterns=["logmind-runbooks-*"],
                template=template,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure runbook template: %s", exc)

    async def ingest_runbook(
        self,
        tenant_id: str,
        service: str,
        title: str,
        markdown_content: str,
        doc_id: str | None = None,
    ) -> str:
        rid = doc_id or str(uuid.uuid4())
        combined_text = f"{title}\n{markdown_content}"
        text_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()

        # Compute vector embedding on thread pool if blocking
        vector = await asyncio.to_thread(
            self.embeddings.get_or_compute_embedding, text_hash, combined_text
        )

        doc = {
            "id": rid,
            "service": service,
            "title": title,
            "content": markdown_content,
            "embedding": vector,
        }

        index = self._index_name(tenant_id)
        _ = await self.es.index(index=index, id=rid, document=doc, refresh=True)
        return rid

    async def search_runbooks(
        self,
        tenant_id: str,
        query: str,
        service: str | None = None,
        limit: int = 5,
    ) -> list[RunbookItem]:
        q_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        vector = await asyncio.to_thread(
            self.embeddings.get_or_compute_embedding, q_hash, query
        )

        knn: dict[str, object] = {
            "field": "embedding",
            "query_vector": vector,
            "k": limit,
            "num_candidates": limit * 5,
        }
        if service:
            knn["filter"] = {"term": {"service": service}}

        body = {"knn": knn, "size": limit}
        index = self._index_name(tenant_id)

        try:
            res = await self.es.search(index=index, body=body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Runbook search error: %s", exc)
            return []

        data = _extract_es_dict(res)
        hits = data.get("hits", {}).get("hits", [])
        results: list[RunbookItem] = []
        for h in hits:
            if not isinstance(h, dict):
                continue
            src = cast(dict[str, object], h.get("_source", {}))
            score = float(h.get("_score", 0.0)) if h.get("_score") is not None else None
            results.append(
                RunbookItem(
                    id=str(src.get("id", h.get("_id", ""))),
                    service=str(src.get("service", "unknown")),
                    title=str(src.get("title", "")),
                    content=str(src.get("content", "")),
                    score=score,
                )
            )

        return results
