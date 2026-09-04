from fastapi import FastAPI

from app.api.dlq import router as dlq_router
from app.api.ingest import router as ingest_router
from app.api.search import router as search_router


def create_app() -> FastAPI:
    app = FastAPI(title="LogMind Ingestion & Search Platform", version="0.1.0")
    app.include_router(ingest_router)
    app.include_router(dlq_router)
    app.include_router(search_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
