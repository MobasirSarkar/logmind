# tests/integration/test_indexer_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.workers.indexer import IndexerWorker

@pytest.mark.asyncio
async def test_indexer_worker_processes_and_routes_dlq_on_error():
    mock_queue = AsyncMock()
    mock_es = AsyncMock()
    mock_es.bulk_index.return_value = 1
    mock_embeddings = MagicMock()
    mock_embeddings.get_or_compute_embedding.return_value = [0.1] * 384
    
    # Return 1 valid log and 1 malformed log
    mock_queue.dequeue_batch.return_value = [
        {
            "timestamp": "2026-09-04T10:30:00Z",
            "level": "ERROR",
            "message": "DB timeout",
            "context": {"tenant_id": "t-1", "service": "order-service"},
            "error": {"error_type": "Timeout", "error_message": "timeout 3000ms"}
        },
        {"invalid": "unparseable_no_timestamp"}
    ]
    
    worker = IndexerWorker(queue_service=mock_queue, es_service=mock_es, embedding_service=mock_embeddings)
    indexed_count, dlq_count = await worker.run_cycle("t-1")
    
    assert indexed_count == 1
    assert dlq_count == 1
    mock_es.bulk_index.assert_called_once()
