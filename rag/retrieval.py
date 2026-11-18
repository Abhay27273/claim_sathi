"""Retrieve relevant chunks from the ingested corpus (rag/ingest/ingest.py) for
grounding draft.py's letters in the actual regulation text, not just the
model's training-data memory of it."""
from functools import lru_cache

from fastembed import TextEmbedding
from qdrant_client import QdrantClient

from rag.ingest.ingest import COLLECTION_NAME, EMBEDDING_MODEL


@lru_cache(maxsize=1)
def _embedder() -> TextEmbedding:
    return TextEmbedding(model_name=EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    return QdrantClient(url="http://localhost:6333")


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    vector = next(iter(_embedder().embed([query]))).tolist()
    results = _client().query_points(collection_name=COLLECTION_NAME, query=vector, limit=top_k).points
    return [{"text": r.payload["text"], "source": r.payload["source"], "score": r.score} for r in results]
