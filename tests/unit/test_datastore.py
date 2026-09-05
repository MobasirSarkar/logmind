import pytest

from app.db import Datastore


@pytest.mark.asyncio
async def test_unified_datastore_creates_all_tables():
    ds = Datastore(database_url="sqlite+aiosqlite:///:memory:")
    await ds.ensure_tables()

    # Verify tables from both correlation and investigation exist on Base.metadata
    from app.db import Base
    table_names = set(Base.metadata.tables.keys())

    # Correlation tables
    assert "services" in table_names
    assert "service_dependencies" in table_names
    assert "incidents" in table_names
    assert "incident_events" in table_names

    # Investigation tables
    assert "investigation_reports" in table_names
    assert "investigation_evidence" in table_names
    assert "investigation_steps" in table_names

    await ds.close()
