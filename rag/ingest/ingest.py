"""Chunk the static corpus (rag/corpus/*.txt) and embed it into Qdrant.

Run once, and again whenever a source document changes:
    python -m rag.ingest.ingest

Uses fastembed (local, ONNX-based, no API key) rather than a Groq/cloud
embedding model -- Groq's self-serve API has no embedding model at all
(confirmed via GET /v1/models, same check that found no vision model there).
BAAI/bge-small-en-v1.5 is English-only; fine for now since the corpus itself
is English-language legal text (IRDAI circulars, Ombudsman Rules). Revisit if
non-English source documents get added.
"""
import re
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
COLLECTION_NAME = "claimsaathi_corpus"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
CHUNK_TARGET_CHARS = 1200


_TOP_LEVEL_SECTION = re.compile(r"^\d+\)\s")


def chunk_text(text: str, source: str) -> list[dict]:
    """Paragraph-aware chunking: split on blank lines, then merge consecutive
    paragraphs up to CHUNK_TARGET_CHARS so a clause doesn't get cut mid-sentence
    by a fixed-size window -- EXCEPT a numbered top-level section marker
    (e.g. "13) Policy/Claim cannot be contested:") always starts a new chunk,
    even under the size limit. Found by testing retrieval quality, not assumed:
    without this, the 60-month moratorium clause -- the single most load-bearing
    clause in this whole product -- ended up merged into a chunk mostly about an
    unrelated portability procedure, diluting it enough that semantic search for
    "moratorium" didn't surface it as a top result."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[dict] = []
    buffer = ""
    for para in paragraphs:
        starts_new_section = bool(_TOP_LEVEL_SECTION.match(para))
        if buffer and (starts_new_section or len(buffer) + len(para) > CHUNK_TARGET_CHARS):
            chunks.append({"text": buffer.strip(), "source": source})
            buffer = ""
        buffer += para + "\n\n"
    if buffer.strip():
        chunks.append({"text": buffer.strip(), "source": source})
    return chunks


def ingest() -> int:
    client = QdrantClient(url="http://localhost:6333")
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)

    all_chunks: list[dict] = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        all_chunks.extend(chunk_text(path.read_text(encoding="utf-8"), source=path.stem))

    vectors = list(embedder.embed([c["text"] for c in all_chunks]))
    dim = len(vectors[0])

    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(id=i, vector=vec.tolist(), payload={"text": c["text"], "source": c["source"]})
            for i, (c, vec) in enumerate(zip(all_chunks, vectors))
        ],
    )
    return len(all_chunks)


if __name__ == "__main__":
    count = ingest()
    print(f"Ingested {count} chunks into Qdrant collection {COLLECTION_NAME!r}")
