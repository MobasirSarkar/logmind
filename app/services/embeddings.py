from collections import OrderedDict

from fastembed import TextEmbedding


class EmbeddingService:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_capacity: int = 10000):
        self.model_name = model_name
        self.cache_capacity = cache_capacity
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._model: TextEmbedding | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def get_or_compute_embedding(self, signature_hash: str, text: str) -> list[float]:
        # Cache hit
        if signature_hash in self._cache:
            self._cache.move_to_end(signature_hash)
            return self._cache[signature_hash]

        # Compute embedding via ONNX
        model = self._get_model()
        vector = [float(v) for v in next(iter(model.embed([text])))]

        # Store in LRU cache
        if len(self._cache) >= self.cache_capacity:
            self._cache.popitem(last=False)
        self._cache[signature_hash] = vector

        return vector
