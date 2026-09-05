import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import (
    close_services,
    get_embedding_service,
    get_es_service,
    get_queue_service,
)
from app.api.dlq import router as dlq_router
from app.api.ingest import router as ingest_router
from app.api.search import router as search_router
from app.workers.indexer import run_worker_loop
from correlation.api import close_database_manager, get_database_manager
from correlation.api import router as correlation_router
from simulator.api import close_simulation_engine
from simulator.api import router as simulator_router

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    queue_service = get_queue_service()
    try:
        await queue_service.redis.ping()
        logger.info("Redis connected successfully")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis connection failed: %s", exc)

    es_service = get_es_service()
    try:
        await es_service.es.info()
        await es_service.ensure_index_template()
        logger.info("Elasticsearch connected and index template ensured")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Elasticsearch connection failed: %s", exc)

    embedding_service = get_embedding_service()
    try:
        await asyncio.to_thread(embedding_service._get_model)
        logger.info("Embedding model warmup success")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding model warmup failed: %s", exc)

    db_manager = get_database_manager()
    try:
        await db_manager.ensure_tables()
        logger.info("Database tables verified")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database table creation failed: %s", exc)

    worker_task = asyncio.create_task(
        run_worker_loop(
            queue_service,
            es_service,
            embedding_service,
        )
    )
    logger.info("Indexer worker started")

    try:
        yield
    finally:
        logger.info("Initiating graceful shutdown...")
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        logger.info("Indexer worker stopped")

        await close_services()
        await close_simulation_engine()
        await close_database_manager()
        logger.info("Services, simulator, and database closed gracefully")

def create_app() -> FastAPI:
    app = FastAPI(
        title="LogMind Ingestion & Search Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(ingest_router)
    app.include_router(dlq_router)
    app.include_router(search_router)
    app.include_router(simulator_router)
    app.include_router(correlation_router)
    return app
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
