import asyncio
import logging
from app.constants import RedisKeyPrefix
from app.models.log import (
    DLQEntry,
    ErrorStage,
    HashType,
    LogFingerprint,
    LogRecord,
)
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import (
    generate_content_hash,
    generate_signature_hash,
    sanitize_error_message,
)
from app.services.queue import QueueService

logger = logging.getLogger("uvicorn.error")


class IndexerWorker:
    def __init__(self, queue_service: QueueService, es_service: ElasticsearchService, embedding_service: EmbeddingService):
        self.queue = queue_service
        self.es = es_service
        self.embeddings = embedding_service

    async def run_cycle(self, tenant_id: str, batch_size: int = 500) -> tuple[int, int]:
        raw_items = await self.queue.dequeue_batch(tenant_id, batch_size=batch_size)
        if not raw_items:
            return 0, 0

        logger.info("Worker picked up %d logs from queue for tenant '%s'", len(raw_items), tenant_id)

        valid_records: list[LogRecord] = []
        dlq_entries: list[DLQEntry] = []

        for item in raw_items:
            try:
                if not isinstance(item, dict):
                    raise TypeError(f"Log payload must be a JSON object, got {type(item).__name__}")
                if "context" not in item:
                    item["context"] = {
                        "tenant_id": tenant_id,
                        "service": item.get("service", "default"),
                        "environment": item.get("environment", "production"),
                    }
                elif isinstance(item["context"], dict) and not item["context"].get("tenant_id"):
                    item["context"]["tenant_id"] = tenant_id

                record = LogRecord.model_validate(item)
                # Compute content hash
                c_hash = generate_content_hash(record)
                
                # Compute embedding (cached by sanitized signature hash)
                raw_text = record.error.error_message if record.error else record.message
                sanitized = sanitize_error_message(raw_text)
                s_hash = generate_signature_hash(sanitized)
                vector = self.embeddings.get_or_compute_embedding(s_hash, sanitized)
                if record.error:
                    record.error.error_signature = sanitized
                record.fingerprint = LogFingerprint(
                    content_hash=c_hash,
                    signature_hash=s_hash,
                    hash_type=HashType.SHA256,
                    embedding=vector
                )
                valid_records.append(record)
            except Exception as e:  # noqa: BLE001
                logger.warning("Log validation/processing failed for tenant '%s': %s (routed to DLQ)", tenant_id, e)
                dlq = DLQEntry(
                    tenant_id=tenant_id,
                    retry_count=3,
                    error_stage=ErrorStage.VALIDATION,
                    last_error=str(e),
                    raw_payload=item
                )
                dlq_entries.append(dlq)

        indexed = 0
        if valid_records:
            indexed = await self.es.bulk_index(valid_records)

        # Store DLQ in Redis list
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
