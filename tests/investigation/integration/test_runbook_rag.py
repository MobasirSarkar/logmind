from unittest.mock import AsyncMock, MagicMock

import pytest

from investigation.runbooks import RunbookItem, RunbookService


@pytest.mark.asyncio
async def test_runbook_ingest_and_search():
    mock_es = AsyncMock()
    mock_embed = MagicMock()
    mock_embed.get_or_compute_embedding.return_value = [0.05] * 384

    service = RunbookService(es_service=mock_es, embedding_service=mock_embed)

    # 1. Ingest runbook
    doc_id = await service.ingest_runbook(
        tenant_id="acme",
        service="payment-service",
        title="Payment Gateway Latency Runbook",
        markdown_content="If Stripe latency exceeds 5000ms, failover to secondary gateway.",
    )
    assert doc_id is not None
    assert mock_es.index.called

    # 2. Search runbook
    mock_es.search.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_id": doc_id,
                    "_score": 0.88,
                    "_source": {
                        "id": doc_id,
                        "service": "payment-service",
                        "title": "Payment Gateway Latency Runbook",
                        "content": "If Stripe latency exceeds 5000ms, failover to secondary gateway.",
                    },
                }
            ],
        }
    }

    results = await service.search_runbooks(
        tenant_id="acme", query="Stripe latency high", service="payment-service"
    )
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, RunbookItem)
    assert item.title == "Payment Gateway Latency Runbook"
    assert item.service == "payment-service"
    assert item.score == 0.88
