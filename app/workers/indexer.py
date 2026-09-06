import asyncio
import logging

from app.constants import RedisKeyPrefix
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import LogEnricher
from app.services.queue import QueueService

logger = logging.getLogger("uvicorn.error")


class IndexerWorker:
    def __init__(
        self,
        queue_service: QueueService,
        es_service: ElasticsearchService,
        embedding_service: EmbeddingService,
        enricher: LogEnricher | None = None,
    ):
        self.queue = queue_service
        self.es = es_service
        self.enricher = enricher or LogEnricher(embedding_service)

    async def run_cycle(self, tenant_id: str, batch_size: int = 500) -> tuple[int, int]:
        raw_items = await self.queue.dequeue_batch(tenant_id, batch_size=batch_size)
        if not raw_items:
            return 0, 0

        logger.info("Worker picked up %d logs from queue for tenant '%s'", len(raw_items), tenant_id)

        valid_records, dlq_entries = self.enricher.enrich_batch(raw_items, tenant_id=tenant_id)

        indexed = await self.es.bulk_index(valid_records) if valid_records else 0

        if dlq_entries:
            _ = await self.queue.push_dlq(tenant_id, dlq_entries)

        logger.info(
            "Worker cycle completed for tenant '%s': %d indexed to Elasticsearch, %d routed to DLQ",
            tenant_id,
            indexed,
            len(dlq_entries),
        )
        return indexed, len(dlq_entries)

async def run_worker_loop(
    queue_service: QueueService,
    es_service: ElasticsearchService,
    embedding_service: EmbeddingService,
    poll_interval: float = 0.5,
) -> None:
    worker = IndexerWorker(queue_service, es_service, embedding_service)
    pattern = f"{RedisKeyPrefix.QUEUE.value}:*"
    logger.info("Indexer worker loop started, polling queues matching '%s'", pattern)
    while True:
        try:
            processed_any = False
            async for key in queue_service.redis.scan_iter(match=pattern):
                tenant_id = key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1]
                indexed, dlq = await worker.run_cycle(tenant_id)
                if indexed > 0 or dlq > 0:
                    processed_any = True
            if not processed_any:
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in indexer worker loop")
            await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    from app.api.deps import get_embedding_service, get_es_service, get_queue_service
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def main() -> None:
        await run_worker_loop(
            get_queue_service(),
            get_es_service(),
            get_embedding_service(),
        )

    asyncio.run(main())
