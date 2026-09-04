from typing import Any


def build_exact_query(query: str, limit: int) -> dict[str, Any]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message", "error.error_message", "error.error_type"],
            }
        },
        "size": limit,
    }

def build_semantic_query(query_vector: list[float], limit: int) -> dict[str, Any]:
    return {
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
        },
        "size": limit,
    }

def build_hybrid_query(query: str, query_vector: list[float], limit: int) -> dict[str, Any]:
    return {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["message", "error.error_message", "error.error_type"],
            }
        },
        "knn": {
            "field": "fingerprint.embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 5,
        },
        "rank": {"rrf": {"window_size": 50, "rank_constant": 60}},
        "size": limit,
    }
