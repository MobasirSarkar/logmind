from unittest.mock import AsyncMock

import pytest

from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine


@pytest.mark.asyncio
async def test_correlation_engine_orchestrates_detection():
    mock_es = AsyncMock()
    # Mock no errors returned
    mock_es.count.return_value = {"count": 0}

    db = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await db.ensure_tables()

    engine = CorrelationEngine(es_service=mock_es, db_manager=db)
    incidents = await engine.evaluate_tenant(tenant_id="t-1")
    assert isinstance(incidents, list)
    assert len(incidents) == 0

    await db.close()
