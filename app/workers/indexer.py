import json
from typing import Any
from app.models.log import DLQEntry, ErrorInfo, ErrorStage, HashType, LogFingerprint, LogLevel, LogRecord
from app.services.elasticsearch import ElasticsearchService
from app.services.embeddings import EmbeddingService
from app.services.normalizer import generate_content_hash, generate_signature_hash, sanitize_error_message
from app.services.queue import QueueService
from app.constants import RedisKeyPrefix

class IndexerWorker:
    def __init__(self, queue_service: QueueService, es_service: ElasticsearchService, embedding_service: EmbeddingService):
        self.queue = queue_service
        self.es = es_service
        self.embeddings = embedding_service

    async def run_cycle(self, tenant_id: str, batch_size: int = 500) -> tuple[int, int]:
        raw_items = await self.queue.dequeue_batch(tenant_id, batch_size=batch_size)
        if not raw_items:
            return 0, 0

        valid_records: list[LogRecord] = []
        dlq_entries: list[DLQEntry] = []

        for item in raw_items:
            try:
                record = LogRecord.model_validate(item)
                # Compute content hash
                c_hash = generate_content_hash(record)
                
                # Check for selective embedding
                vector = None
                s_hash = None
                if record.level in (LogLevel.ERROR, LogLevel.FATAL) or record.error is not None:
                    err_msg = record.error.error_message if record.error else record.message
                    sanitized = sanitize_error_message(err_msg)
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
            except Exception as e:
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
            dlq_key = RedisKeyPrefix.DLQ.for_tenant(tenant_id)
            await self.queue.redis.lpush(dlq_key, *[json.dumps(d.model_dump(mode="json")) for d in dlq_entries])

        return indexed, len(dlq_entries)
