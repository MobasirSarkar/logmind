# tests/unit/test_config.py
from app.config import Settings

def test_settings_load_defaults():
    settings = Settings(
        REDIS_URL="redis://localhost:6379/0",
        ELASTICSEARCH_URL="http://localhost:9200",
        QUEUE_MAX_DEPTH=50000,
        EMBEDDING_MODEL_NAME="BAAI/bge-small-en-v1.5"
    )
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.ELASTICSEARCH_URL == "http://localhost:9200"
    assert settings.QUEUE_MAX_DEPTH == 50000
    assert settings.EMBEDDING_MODEL_NAME == "BAAI/bge-small-en-v1.5"
