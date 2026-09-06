from typing import Annotated

from fastapi import Depends, Query

from app.api.deps import EsDep
from correlation.db import DatabaseManager
from correlation.engine import CorrelationEngine
from correlation.log_store import ESLogStore
from correlation.models import IncidentStatus

_db_manager: DatabaseManager | None = None
_correlation_engine: CorrelationEngine | None = None


def get_database_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_correlation_engine(
    es: EsDep,
    db: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> CorrelationEngine:
    global _correlation_engine
    if _correlation_engine is None:
        log_store = ESLogStore(es.es)
        _correlation_engine = CorrelationEngine(
            es_service=es.es, db_manager=db, log_store=log_store
        )
    return _correlation_engine


async def close_database_manager() -> None:
    global _db_manager, _correlation_engine
    if _db_manager is not None:
        await _db_manager.close()
        _db_manager = None
    _correlation_engine = None


DbDep = Annotated[DatabaseManager, Depends(get_database_manager)]
CorrelationDep = Annotated[CorrelationEngine, Depends(get_correlation_engine)]
StatusQuery = Annotated[IncidentStatus | None, Query()]
