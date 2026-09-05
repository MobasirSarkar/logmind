from enum import Enum


class RedisKeyPrefix(str, Enum):
    QUEUE = "logmind:queue"
    DLQ = "logmind:dlq"

    def for_tenant(self, tenant_id: str) -> str:
        return f"{self.value}:{tenant_id}"

class ESIndexPrefix(str, Enum):
    LOGS = "logmind-logs"

    def for_tenant(self, tenant_id: str) -> str:
        return f"{self.value}-{tenant_id}"


class EmbeddingModel(str, Enum):
    BGE_SMALL_EN = "BAAI/bge-small-en-v1.5"
