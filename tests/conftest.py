from collections.abc import AsyncGenerator

import pytest

from app.db import close_datastore
from correlation.api import close_database_manager
from investigation.api import close_investigation_services


@pytest.fixture(autouse=True)
async def cleanup_db_connections() -> AsyncGenerator[None]:
    yield
    await close_investigation_services()
    await close_database_manager()
    await close_datastore()
