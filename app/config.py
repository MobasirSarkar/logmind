from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    REDIS_URL: str = "redis://localhost:6379/0"
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    QUEUE_MAX_DEPTH: int = 50000
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    API_KEY: str = "lmd_dev_key"

settings = Settings()
