from collections import OrderedDict
from collections.abc import Iterable
from typing import cast

from fastembed import TextEmbedding

from app.constants import EmbeddingModel


class EmbeddingService:
    def __init__(
        self,
        model_name: str | EmbeddingModel = EmbeddingModel.BGE_SMALL_EN,
        cache_capacity: int = 10000,
    ):
        self.model_name: str = (
            model_name.value if isinstance(model_name, EmbeddingModel) else str(model_name)
        )
        self.cache_capacity: int = cache_capacity
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
        raw_output = next(iter(model.embed([text])))
        vector = [float(v) for v in cast(Iterable[float], raw_output)]

        # Store in LRU cache
        if len(self._cache) >= self.cache_capacity:
            _ = self._cache.popitem(last=False)
        self._cache[signature_hash] = vector

        return vector
