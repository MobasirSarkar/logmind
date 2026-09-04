from fastapi import FastAPI
from app.api.ingest import router as ingest_router

def create_app() -> FastAPI:
    app = FastAPI(title="LogMind Ingestion & Search Platform", version="0.1.0")
    app.include_router(ingest_router)
    return app

app = create_app()
