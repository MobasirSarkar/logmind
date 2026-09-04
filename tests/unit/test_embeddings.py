# tests/unit/test_embeddings.py
from unittest.mock import MagicMock
from app.services.embeddings import EmbeddingService

def test_embedding_service_dimension_and_cache():
    service = EmbeddingService(model_name="BAAI/bge-small-en-v1.5")
    
    # Mock model encode method to test cache logic without ONNX overhead in unit test
    fake_vector = [0.1] * 384
    service._model = MagicMock()
    service._model.embed = MagicMock(return_value=iter([fake_vector]))
    
    vec1 = service.get_or_compute_embedding("sig-123", "Database connection pool exhausted")
    assert len(vec1) == 384
    assert service._model.embed.call_count == 1
    
    # Second call with identical signature_hash must hit cache and NOT call model.embed
    vec2 = service.get_or_compute_embedding("sig-123", "Database connection pool exhausted")
    assert vec2 == vec1
    assert service._model.embed.call_count == 1
