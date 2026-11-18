# ClaimSaathi

AI copilot that turns a rejected or short-paid Indian health-insurance claim into an
evidence-backed, rule-cited escalation through the insurer's grievance cell, IRDAI's
Bima Bharosa, and the Insurance Ombudsman.

Full product and technical plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) --
**read the PIVOT LOG and SECURITY HARDENING PASS notes near the top first**, they
correct several things the rest of the document still describes in its original form.
a
## Quickstart

```bash
cp .env.example .env
# Fill in: GROQ_API_KEY(2/3), SARVAM_API_KEY, RAZORPAY_KEY_ID/SECRET, GATEWAY_API_KEY
# (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"),
# and ALLOW_DEV_OTP=true (no real MSG91 account yet -- see services/gateway/otp.py)

python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt

docker compose -f infra/docker-compose.yml up -d   # Postgres, Redis, Qdrant
# If port 5432 is already taken by a native Postgres install on your machine,
# infra/docker-compose.yml maps the container to host port 5433 instead -- the
# DATABASE_URL in .env.example already expects that port.
docker exec -i <postgres-container-name> psql -U claimsaathi -d claimsaathi < db/schema.sql

python -m rag.ingest.ingest   # one-time: embed the Master Circular + Ombudsman Rules into Qdrant

# Run from the repo root so `services.*` absolute imports resolve:
uvicorn services.gateway.main:app --reload
```

Every `/cases*` and `/review-queue*` request needs the `X-API-Key` header set to your
`GATEWAY_API_KEY`. Request flow: `POST /cases` (free preview) → `POST /cases/{id}/orders`
(Razorpay order, tier=`gro_letter` or `full_ladder`) → client completes checkout →
`POST /cases/{id}/draft` (signature-verified payment required) returns the GRO letter
→ `POST /cases/{id}/escalate` (stage=`bima_bharosa`/`ombudsman`, needs a paid
`full_ladder` tier) for further stages.

## Layout

| Path | Purpose |
|---|---|
| `services/gateway/main.py` | FastAPI entrypoint: intake, payments, escalation, human-review queue, OTP auth |
| `services/gateway/security.py` | API-key auth, Redis rate limiting, upload validation, path-traversal-safe filenames |
| `services/gateway/razorpay_client.py` | Order creation + signature verification -- the real security boundary on payment |
| `services/gateway/otp.py` | Phone-OTP auth via MSG91 -- dev-mode tested, real SMS needs an MSG91 account (none yet) |
| `services/orchestrator/` | Two LangGraph state machines: `build_preview_graph()` (free) and `build_draft_graph()` (paid) |
| `services/orchestrator/nodes/ocr.py` | Tesseract OCR -- the reading step, since no vision model is available (see PIVOT LOG) |
| `services/orchestrator/prompt_guard.py` | Untrusted-document-content framing shared by classify/extract/draft |
| `services/rules_engine/` | Deterministic date/clause checks -- no LLM, see section 5 |
| `services/voice/sarvam_client.py`, `pipeline.py` | Sarvam STT/TTS + the Pipecat conversation pipeline -- constructs and links correctly against real keys; not live-tested (no audio hardware in this dev environment) |
| `services/scheduler/deadlines.py` | GRO 30-day / Ombudsman 1-year deadline tracking -- a polling worker, run separately: `python -m services.scheduler.deadlines` |
| `rag/` | Real IRDAI Master Circular + Ombudsman Rules text (extracted from the actual PDFs), chunked, embedded locally (fastembed, no API key), retrieved into `draft.py` for grounded citations |
| `apps/web/` | Next.js frontend -- written, not run (sandbox-specific npm registry block, see `apps/web/README.md`) |
| `apps/whatsapp-webhook/` | Not yet built |
| `db/schema.sql` | Starting schema; superseded by Alembic migrations post-v0 |
| `config/models.yaml` | Task -> Groq model routing (edit here when a model is renamed/retired) |
| `eval/golden_set/` | Anonymised real cases for regression-testing the pipeline -- not yet populated |

## What's actually tested vs. just written

Everything in `services/orchestrator/`, `services/gateway/`, `services/scheduler/`,
and `rag/` has been run against the real Groq/Sarvam/Razorpay/Qdrant stack at least
once, not just unit-tested in isolation -- including auth rejection, rate-limit
enforcement, upload validation, path-traversal filenames, cross-case payment-reuse
attempts, fraud-allegation routing to a human-review queue, escalation-stage
sequencing (can't skip to Ombudsman before Bima Bharosa), deadline computation, OTP
request/verify/session issuance, and RAG-grounded letter drafting that correctly
resolved "PMC" and "CRC" from the real regulatory text instead of the model guessing.

**Not tested, said plainly:**
- A genuine end-to-end browser checkout -- no legitimate server-only way to simulate
  Razorpay's "captured" payment state (that's the signature check's whole point).
- The web app (`apps/web/`) -- written, reviewed, never executed; `npm install` hits
  a sandbox-specific 403 from the npm registry that a normal machine shouldn't see.
- A live voice conversation -- the Pipecat pipeline constructs and links correctly,
  but running it needs a real audio transport (mic/speaker or a browser WebRTC
  session), neither of which exists in this terminal sandbox.
- Real MSG91 SMS sending -- the OTP flow is fully tested in dev mode (`ALLOW_DEV_OTP`);
  no MSG91 account exists yet to test actual SMS delivery.
- Hindi OCR (no tessdata pack installed; English only so far) and real insurer
  document scans (only synthetic test PDFs so far -- real-world OCR quality on messy
  scans remains the single biggest open unknown in the whole plan).
