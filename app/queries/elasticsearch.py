def build_exact_query(query: str, limit: int) -> dict[str, object]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message^3", "error.error_message^3", "error.error_type^2", "context.service"],
            }
        },
        "size": limit,
    }

def build_semantic_query(
    query_vector: list[float],
    limit: int,
    similarity_threshold: float = 0.65,
) -> dict[str, object]:
    return {
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
            "similarity": similarity_threshold,
        },
        "size": limit,
    }

def build_hybrid_query(
    query: str,
    query_vector: list[float],
    limit: int,
    similarity_threshold: float = 0.65,
) -> dict[str, object]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message^3", "error.error_message^3", "error.error_type^2", "context.service"],
                "boost": 0.7,
            }
        },
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
            "similarity": similarity_threshold,
            "boost": 0.3,
        },
        "size": limit,
    }
