# Ingestion

`ingest.py` is real, tested code. Run it to (re-)build the Qdrant collection:

    python -m rag.ingest.ingest

Chunks `rag/corpus/*.txt` on paragraph boundaries, forcing a new chunk at every
numbered top-level section marker (e.g. "13) Policy/Claim cannot be
contested:") even under the size target -- found by testing retrieval quality,
not designed in up front: without that rule, the 60-month moratorium clause
(the single most load-bearing clause in this product) got merged into a chunk
mostly about an unrelated portability procedure, which diluted it enough that
semantic search for "moratorium" didn't surface it as a top result.

Embeds with `fastembed` (BAAI/bge-small-en-v1.5, local ONNX, no API key --
Groq's self-serve API has no embedding model at all). English-only; the corpus
itself is English-language legal text, so this hasn't been a real limitation
yet, but revisit if a non-English source document gets added.

Simpler than the plan's original "hybrid dense+sparse retrieval (RRF)" design
(IMPLEMENTATION_PLAN.md section 2) -- plain dense-vector search only, no
sparse/keyword side or fusion. That was a deliberate scope cut, not an oversight:
dense search alone already correctly surfaces the moratorium and CRC/PMC
clauses for the queries tested so far (see rag/retrieval.py's docstring-level
testing). Worth revisiting once there's a larger corpus (award precedents,
insurer playbooks) where keyword matching might start pulling its weight.
