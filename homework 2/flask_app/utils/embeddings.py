
import math
import os

from fastembed import TextEmbedding


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_embedder = None


def get_embedder():
    """Load the embedding model once and reuse it."""
    global _embedder

    if _embedder is None:
        model_name = os.getenv(
            "EMBEDDING_MODEL",
            DEFAULT_EMBEDDING_MODEL
        )
        _embedder = TextEmbedding(model_name=model_name)

    return _embedder


def embed_text(text):
    """Convert text into a validated numerical embedding."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Cannot embed empty text.")

    model = get_embedder()
    vectors = list(model.embed([text.strip()]))

    if not vectors:
        raise ValueError("Embedding model returned no vector.")

    vector = [float(value) for value in vectors[0]]

    if not vector:
        raise ValueError("Embedding vector is empty.")

    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding contains invalid numbers.")

    if not any(value != 0.0 for value in vector):
        raise ValueError("Embedding vector contains only zeros.")

    return vector


def cosine_similarity(vector_a, vector_b):
    """Calculate cosine similarity between two vectors."""
    if len(vector_a) != len(vector_b):
        raise ValueError("Embedding dimensions do not match.")

    dot_product = sum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        raise ValueError("Cannot compare zero vectors.")

    return dot_product / (norm_a * norm_b)


def embed_records(records):
    """Create embeddings for a list of text records."""
    results = []

    for record in records:
        text = record.get("text", "")

        vector = embed_text(text)

        results.append({
            "table_name": record["table_name"],
            "record_id": record["record_id"],
            "embedded_text": text,
            "vector": vector
        })

    return results


def semantic_search(db, query_text, limit=5):
    import json

    query_vector = embed_text(query_text)

    rows = db.query(
        "SELECT table_name, record_id, embedded_text, vector_json FROM embeddings"
    )

    results = []

    for row in rows:
        stored_vector = json.loads(row["vector_json"])
        score = cosine_similarity(query_vector, stored_vector)

        results.append({
            "table_name": row["table_name"],
            "record_id": row["record_id"],
            "embedded_text": row["embedded_text"],
            "score": score
        })

    results.sort(key=lambda item: item["score"], reverse=True)

    return results[:limit]
