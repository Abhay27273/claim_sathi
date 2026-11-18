# ClaimSaathi — End-to-End Implementation Plan (Grok / xAI Edition)

This adapts the ClaimSaathi concept from the research brief into a buildable plan that uses the **xAI Grok API** as the primary LLM/vision provider instead of Gemini/Claude. Everything that isn't an LLM call (rules engine, deadline logic, Hindi/Hinglish voice, databases, payments) is unchanged from the original brief — only the reasoning/drafting/OCR layer moves to Grok.

> **Pricing/model-name caveat:** xAI ships new Grok point-releases every few months and renames/retires models (e.g. `grok-4-fast` was retired in May 2026 in favor of newer budget models). Treat every model name and price below as "best known at time of writing, 2026-11-03" and re-verify against `GET https://api.x.ai/v1/models` before locking a build. Sources: [xAI model docs](https://docs.x.ai/docs/models), [pricepertoken.com](https://pricepertoken.com/pricing-page/model/xai-grok-4-fast), [opslyft.com](https://www.opslyft.com/blog/ai-grok-api-pricing-2026).

> **PIVOT LOG (2026-11-17) — read this before trusting anything below about the model provider.** The sections below describe the *original* design (xAI Grok, vision-based OCR). The actual running code pivoted away from both:
> 1. **Provider: xAI → Groq Cloud.** The keys actually obtained were Groq Cloud keys (`gsk_...`, api.groq.com) — a different company from xAI, despite the similar name. `services/orchestrator/groq_client.py` is the live client (OpenAI-compatible, rotates across up to three `GROQ_API_KEY*` keys on rate limits); `grok_client.py` is dormant xAI code kept in case that provider comes back into play. Live models in use, confirmed against `GET https://api.groq.com/openai/v1/models` on three separate keys: `openai/gpt-oss-20b` (classify/extract/evidence_gap) and `openai/gpt-oss-120b` (draft). `config/models.yaml` is the source of truth, not this document.
> 2. **Reading: vision → OCR.** No vision model is active on Groq's self-serve API (confirmed three times). `services/orchestrator/nodes/ocr.py` (Tesseract, installed via winget) now sits between PREPROCESS and CLASSIFY, converting rasterized pages to plain text; CLASSIFY/EXTRACT reason over that text instead of page images. Section 4.3's vision-specific preprocessing (base64 data URLs, JPG/PNG-only) is dormant code in `classify.py`/`extract.py`, not deleted in case a vision model becomes available later.
>
> Everything downstream of that (rules engine, LangGraph wiring, Postgres schema, validator design) held up and is real, tested code — verified end-to-end through a full `build_graph()` run against live Groq calls, not just unit-level stubs. Three real bugs were found and fixed by that testing, worth knowing about if you touch these files: `.message.parsed` doesn't exist on plain `create()` responses (use `json.loads(.content)`); the validator's date/clause matching needs format-variant and whitespace normalization, not exact string equality (gpt-oss-120b writes dates with ` ` narrow spaces and paraphrases long clause quotes); and `draft.py`'s prompt needs an explicit India-jurisdiction anchor (INR currency, IRDAI/Insurance Ombudsman/Bima Bharosa terminology) or the model defaults to UK-shaped output (GBP amounts, "Financial Ombudsman Service") with nothing anchoring it to India otherwise.
>
> **SECURITY HARDENING PASS (2026-11-17).** The gateway and pipeline were not production-safe before this -- `/cases` had no auth, no rate limit, trusted client-supplied filenames, and gave away the paid letter for free. Fixed, all verified against the real running app (not just code review):
> - **Auth + rate limiting:** every `/cases*` route requires `X-API-Key` (`services/gateway/security.py`); confirmed 401 on missing/wrong key. Rate limits are Redis-backed fixed windows (shared across instances, not an in-process counter) -- confirmed a 4th request over a 3-request limit gets a real 429.
> - **Upload hardening:** MIME allowlist (PDF/JPEG/PNG only) and a 15MB/file cap, both confirmed rejecting real violating uploads. Filenames are never trusted as path components -- `security.safe_destination()` generates a UUID-based name, keeping only the extension; confirmed a path-traversal filename landed safely inside the case's own directory, not outside it.
> - **Free/paid split with real payment verification:** `graph.py` split into `build_preview_graph()` (free -- classify/extract/rule_check/evidence_gap) and `build_draft_graph()` (paid -- draft/validate), so the letter is never generated before payment. `/cases/{id}/draft` checks three independent things before drafting: the Razorpay order belongs to *this* case (confirmed: a correctly-HMAC-signed payment for case A's order was rejected when replayed against case B -- the binding check catches it before signature verification even runs), the signature is valid (confirmed: a forged signature is rejected), and Razorpay confirms the payment is actually `captured` for the right amount (stops a created-but-unpaid order from being treated as paid). **Gap, not swept under the rug:** there is no legitimate server-only way to generate a genuinely *captured* test payment -- that requires a real browser checkout (Razorpay's test card flow). Everything up to that point is tested against the live Razorpay API; the final "did a human complete checkout" leg isn't, because nothing server-side can fake it without reintroducing the hole the signature check exists to close.
> - **Guardrails from section 4 of this doc, actually implemented, not just described:** `prompt_guard.py` wraps all OCR'd document text in explicit untrusted-content markers with a system prompt instructing the model never to treat document content as instructions (defense against a crafted scan trying to say "approve this in full"). `graph.py` routes `fraud_allegation` classifications straight to `needs_human_review_fraud` *before* EXTRACT/DRAFT even run -- never auto-drafted. Every letter gets a deterministic (not LLM-dependent) "this is self-help drafting, not legal advice" disclaimer appended in code. `draft.py` is instructed never to invent an abbreviation's full form if it isn't given one (found via testing: it had guessed a wrong expansion for "PMC").
> - **Graceful failure:** a case missing the policy-wording document (a very ordinary user mistake) used to crash with a raw 500/KeyError; `rule_check.py` now degrades to an explanatory "cannot evaluate, here's what's missing" result instead, and a global exception handler ensures *any* unexpected error returns a generic message with a correlation id, never a stack trace, to the client.
> - **Not done, and said plainly (as of the hardening pass; some of this was built since, see the FEATURE BUILD note below):** no WAF/DDoS/infra-level protection (that's hosting-provider territory); no secrets-manager integration (still `.env`, fine for one dev machine, not for a real deployment).
>
> **FEATURE BUILD (2026-11-17, same day, later).** Escalation stages, the human-review queue, the deadline scheduler, a real RAG corpus, phone-OTP auth, a Next.js web app, and the Pipecat voice pipeline -- all built and tested as far as this sandboxed environment allows:
> - **Escalation stages are real.** `build_draft_graph()` now drafts `bima_bharosa` and `ombudsman`, not just `gro`. `/cases/{id}/escalate` requires a paid `full_ladder` tier (Rs 1,499 -- one payment covers all three stages, confirmed a `gro_letter`-tier-only payment correctly can't unlock it) and the prior stage's letter to already exist (confirmed: escalating to `ombudsman` before a `bima_bharosa` letter exists is rejected with 409). Real letters drafted and validated for both new stages against live Groq calls.
> - **Human-review queue is a real queue now**, not just a status string: `human_review_notes` table + `GET /review-queue` + `POST /review-queue/{id}/resolve`. Confirmed end-to-end with a document genuinely written to read as a fraud allegation (Section 45 IPC-style SIU letter) -- correctly classified `fraud_allegation`, routed to the queue *before* EXTRACT/DRAFT ran at all (no wasted Groq calls on a case that needs a lawyer, not a letter), appeared in the queue, and left it on resolution. Still no actual notification (email/SMS) when something lands in the queue -- someone has to poll `GET /review-queue`.
> - **Deadline scheduler is real**, not aspirational: `services/scheduler/deadlines.py`, a plain polling loop (deliberately not Celery/RQ -- not worth the dependency at this volume), confirmed to detect an overdue deadline, mark it, and never re-fire on the same one. `schedule_gro_deadline`/`schedule_ombudsman_deadline` are wired into `/cases/{id}/draft`; confirmed the computed due dates are correct (30 days from now; exactly 1 year from the real `rejection_date`). No notification channel exists yet (logs a warning) -- there's nothing to notify *through* (no WhatsApp, no email) until one of those gets built.
> - **RAG corpus is real primary-source text, not paraphrase.** `rag/corpus/*.txt` is the IRDAI Master Circular (29 May 2024) and Insurance Ombudsman Rules 2017, extracted with `pypdfium2` from the actual PDFs. This resolved a real unknown from earlier in the session: "PMC" is the **Product Management Committee**, with CRC as its three-member claims sub-group -- previously the code was instructed to never guess that expansion; now it's grounded in the primary source. Chunking required a fix found by testing, not designed up front: naive paragraph-merging buried the 60-month moratorium clause (the single most load-bearing clause in this product) inside a chunk mostly about an unrelated portability procedure, which kept it from surfacing for "moratorium" queries until chunks were forced to split at numbered section markers too. `draft.py` now retrieves and cites this real text; degrades to no-retrieval (not a crash) if Qdrant/fastembed hiccups. Scope cut, deliberate: dense-vector search only, no hybrid sparse/RRF as this doc's section 2 originally described -- revisit once the corpus grows past these two documents.
> - **Phone-OTP auth exists and is tested in dev mode.** `services/gateway/otp.py` + `/auth/request-otp` + `/auth/verify-otp`, confirmed: wrong OTP rejected, correct OTP issues a session token, the same OTP can't be reused, and -- deliberately -- the dev-mode fallback that returns the OTP in the response requires **both** no `MSG91_AUTH_KEY` **and** an explicit `ALLOW_DEV_OTP=true`, not just a missing key; confirmed that omitting `ALLOW_DEV_OTP` fails loudly (500) rather than silently running insecure. No real MSG91 account exists yet, so actual SMS delivery is unverified.
> - **Voice pipeline constructs correctly against real services**, not just hoped to: `services/voice/pipeline.py` wires Sarvam STT -> Groq LLM -> Sarvam TTS via Pipecat 1.16.0, confirmed all five stages link with zero errors and zero deprecation warnings against the real API keys. Built against pipecat's *actual installed* API, which turned out to differ from what docs.pipecat.ai currently documents (`pipecat.context.*` doesn't exist in 1.16.0; the real path is `pipecat.processors.aggregators.llm_context`/`llm_response_universal`) -- found by introspecting the installed package, not by trusting the docs site. **Not tested:** an actual live conversation -- that needs a real audio transport (mic/speaker or browser WebRTC), and this sandbox has neither.
> - **Web app is written, not run.** Full Next.js App Router frontend (upload -> preview -> Razorpay Checkout -> letter -> escalate), with server-side API-route proxies so `GATEWAY_API_KEY` never reaches the browser. `npm install` hits a sandbox-specific 403 from the npm registry -- `curl` to the identical URL gets 200, which points at a TLS-fingerprint-level filter rather than a real outage; the standard fixes (`--use-system-ca`, `--strict-ssl=false`) didn't change it. Pushing further into TLS-fingerprint spoofing would mean working around a security boundary rather than an artifact, so this was left as a flagged gap: install and run on a machine with normal registry access.

---

## 0. What changes vs. the original brief

| Layer | Original brief | This plan |
|---|---|---|
| Document OCR + classification | Gemini 3.1 Flash-Lite | **Grok (budget tier, e.g. `grok-4.3`)**, vision input |
| Argument drafting (final letters) | Gemini 3.1 Pro | **Grok flagship (e.g. `grok-4.7`)** |
| Hindi/Hinglish voice STT/TTS | Sarvam Saaras/Bulbul | **Unchanged — Sarvam** (Grok has no voice I/O) |
| Self-hosted Hindi fallback | Sarvam-30B/105B on vLLM | **Unchanged**, kept as a fallback/cost-control path, not primary |
| Everything else (rules engine, LangGraph, Postgres, Redis, Qdrant, Neo4j, Razorpay, WhatsApp) | — | **Unchanged** |

The single biggest engineering consequence of this swap: **Grok's vision endpoint only accepts JPG/PNG, not PDF**, and has no first-class "read this scanned document" OCR product the way some competitors do. Section 4.3 below covers the preprocessing this requires.

---

## 1. Scope recap (MVP)

Health-insurance claim rejections only (not e-commerce/banking). Top 8 rejection reasons: pre-existing-disease non-disclosure, waiting period, "not medically necessary", room-rent/proportionate deduction, consumables/non-payables, missing documents/unanswered query, policy-exclusion clause, fraud allegation. Top 6 insurers by complaint volume get insurer-specific letter templates first.

Journey: upload/WhatsApp rejection letter + policy + discharge papers → free "Case Strength" report → paid grievance-officer letter → deadline tracking → Bima Bharosa escalation → Ombudsman escalation → outcome logged.

---

## 2. System architecture

```
 [WhatsApp Business API]      [Web app: Next.js]      [Voice: Pipecat + Sarvam STT/TTS]
            \                        |                          /
             +---------------- FastAPI gateway (auth, rate-limit) ----------------+
                                      |
                        LangGraph Case State Machine (Python, checkpointed in Postgres)
   INTAKE -> PREPROCESS -> CLASSIFY -> EXTRACT -> RULE_CHECK -> EVIDENCE_GAP -> DRAFT -> VALIDATE
      -> USER_APPROVE -> TRACK(GRO 30d) -> ESCALATE(Bima Bharosa) -> OMBUDSMAN(1yr) -> OUTCOME
         |            |              |                 |               |            |
   PDF->PNG      Grok vision      Hybrid RAG       Deterministic    Grok flagship  Validator:
   rasterizer    (budget model)   (Qdrant dense    rules engine     drafter,       string-match
   (pypdfium2/   classify +      +sparse, RRF):    (plain Python:   structured     every quoted
   pdf2image)    structured      policy wording,   dates,           JSON output    clause against
                 field extract   IRDAI circulars,  moratorium,      per letter     source; recompute
                 (JSON mode)     ombudsman awards,  waiting period, section        every date;
                                 insurer playbooks  CRC requirement,               reject & regen
                                                     PED relevance)                 loop (max 2)
                                      |
        Neo4j (v2): clause <-> exclusion <-> condition <-> rejection-reason graph
        PostgreSQL: users, cases, documents, deadlines, payments, audit log
        Redis: job queue (Celery/RQ), reminder scheduling, rate-limit counters
        Object store (India region, encrypted at rest): raw documents, auto-purge policy
        Observability: structured logs + Grafana; per-case Grok token-cost dashboard
        Payments: Razorpay (UPI) | Auth: phone OTP (MSG91/Firebase)
```

---

## 3. Model selection strategy on Grok

| Task | Model class | Why | Est. price (per 1M tok, in/out)* |
|---|---|---|---|
| Page classification, field extraction, evidence-gap check | Budget/efficient tier, 1M context (e.g. `grok-4.3` or successor) | High volume, structured-output tasks don't need top-tier reasoning; 1M context swallows a whole policy wording in one pass | ~$1.25 / $2.50 |
| Final letter drafting (GRO, Bima Bharosa, Ombudsman submission) | Flagship tier (e.g. `grok-4.7`) | Legal-argument quality and clause-citation discipline matter most here; low volume (3 letters/case) keeps cost small | ~$2–4 / $6–12 (two-tier pricing above ~200k context — see note) |
| Hindi/Hinglish voice intake transcription + TTS | Sarvam Saaras / Bulbul | Grok has no audio I/O | ~₹30/hr STT, ~₹30/10K chars TTS |
| Self-hosted Hindi drafting fallback at volume | Sarvam-30B/105B on vLLM | Cost control once case volume justifies a GPU; also a vendor-outage fallback for Grok | infra cost only |

\* Flagship Grok models use **two-tier pricing**: cost per token steps up once the prompt crosses a context threshold (reported around 128k–200k tokens depending on model). **Design implication:** never send raw 30–60 page documents into the flagship drafting call. Pass it only the *structured facts* that CLASSIFY/EXTRACT already pulled out (rejection category, dates, clause text snippets, evidence list) — a few thousand tokens, not the whole dossier. This keeps every drafting call in the cheap pricing tier and is good practice regardless of pricing.

**Model router:** build a thin `grok_client.py` wrapper that takes a `task` enum (`classify`, `extract`, `draft`, `validate`) and resolves it to a model name via a config file, not hardcoded strings. When xAI renames/retires a model (as it did with `grok-4-fast` in May 2026), you change one YAML line.

---

## 4. Grok API integration details

### 4.1 Auth & SDK
- Get an API key from the xAI console (console.x.ai) → stored as `XAI_API_KEY` env var, never committed.
- The xAI API is **OpenAI-compatible**: use the standard `openai` Python/Node SDK pointed at `base_url="https://api.x.ai/v1"`. This means LangGraph's existing OpenAI-style tool-calling nodes work with minimal changes.
- Use a dedicated billing/org API key for production vs. a personal dev key; set per-key spend caps in the xAI console as a cost guardrail.

### 4.2 Structured outputs & function calling
- Use Grok's `response_format: {type: "json_schema", ...}` (structured outputs) for every extraction/classification call — never free-text parsing. Define one JSON schema per task: `RejectionClassification`, `ExtractedFacts`, `EvidenceGapList`, `DraftLetter`.
- Use function/tool calling for the rules engine handoff: the EXTRACT node returns structured dates and facts as a tool call payload, which the deterministic Python rules engine consumes directly (no LLM math on dates — see §5).

### 4.3 Vision/OCR pipeline (the main Grok-specific build item)
Grok vision accepts **JPG/PNG only, ≤20MB per image, no documented cap on image count per request**. Most real input (rejection letters, policy wordings) arrives as PDF or a WhatsApp photo.

1. **WhatsApp photo** → already JPG/PNG, send directly.
2. **PDF upload** → rasterize each page to PNG server-side (`pypdfium2` or `pdf2image`+poppler) at ~150–200 DPI before any Grok call. Tag each image with its source page number so later clause citations can reference "Policy wording, p.14".
3. **Batching:** send a document's pages as multiple image blocks in one Grok request where the page count keeps the request under the cheap pricing tier; otherwise chunk by logical section (schedule of benefits, exclusions, endorsements) and merge results.
4. **Low-quality scans:** if Grok's extracted text confidence is low (heuristic: extracted field is empty/garbled on a field the rules engine needs, e.g. a date), fall back to a dedicated OCR pass (Tesseract or a cloud OCR) on that page and re-prompt Grok with the OCR text instead of the image.
5. Keep the **rasterized PNGs**, not just Grok's output, in the encrypted object store — needed for the validator step and for human review.

### 4.4 Reliability
- Wrap every Grok call with retry + exponential backoff (rate limits, transient 5xx) and a circuit breaker; LangGraph node should checkpoint before and after the call so a case can resume mid-pipeline.
- Log token usage per call (prompt, completion, cached-if-any) into Postgres for the cost dashboard in §14.
- No confirmed India-region hosting for the xAI API as of now — see §13 for the data-residency implication.

---

## 5. Non-LLM components (unchanged from original brief)

- **Rules engine** — plain Python, not an LLM: moratorium-date arithmetic (60 months continuous/ported coverage), waiting-period checks, CRC-approval requirement flag, "insurer must cite specific clause" check, cashless-TAT breach check (1hr/3hr). This is the reliability backbone — dates and legal thresholds must never depend on a model getting arithmetic right.
- **Deadline engine** — GRO 30-day clock, Ombudsman 1-year window, reminders via Redis-scheduled jobs → WhatsApp/push.
- **Hybrid RAG (Qdrant)** — dense + sparse retrieval with reciprocal rank fusion over: policy wordings (user-specific), IRDAI Master Circular + Ombudsman Rules (static corpus), a growing library of published Ombudsman awards (precedent), insurer-specific playbooks.
- **Validator** — after DRAFT, every quoted clause must string-match verbatim against the source document text (not just "sound right" to the LLM); every date in the letter is recomputed independently by the rules engine, not trusted from the draft. Two failed regenerations → route to human reviewer queue.

---

## 6. Repo structure

```
claimsaathi/
├── apps/
│   ├── web/                # Next.js app (case intake, dashboard, payments)
│   └── whatsapp-webhook/   # Meta Cloud API / BSP webhook receiver
├── services/
│   ├── gateway/            # FastAPI: auth, rate-limit, routes to orchestrator
│   ├── orchestrator/       # LangGraph state machine + node implementations
│   │   ├── nodes/
│   │   │   ├── preprocess.py   # PDF->PNG rasterization
│   │   │   ├── classify.py     # Grok budget-tier call
│   │   │   ├── extract.py      # Grok budget-tier call, structured output
│   │   │   ├── rule_check.py   # pure Python, no LLM
│   │   │   ├── evidence_gap.py
│   │   │   ├── draft.py        # Grok flagship call
│   │   │   └── validate.py     # citation/date validator + regen loop
│   │   └── grok_client.py      # model router, retries, token logging
│   ├── rules_engine/       # moratorium/waiting-period/CRC logic, unit-tested heavily
│   ├── voice/               # Pipecat + Sarvam STT/TTS
│   └── scheduler/           # Redis-backed deadline reminders (Celery/RQ)
├── rag/
│   ├── ingest/              # scripts to chunk+embed Master Circular, Ombudsman Rules, awards
│   └── corpus/              # static source documents (versioned, not secrets)
├── db/
│   ├── migrations/          # Postgres (Alembic)
│   └── schema.sql
├── infra/
│   ├── docker-compose.yml   # Postgres, Redis, Qdrant, (Neo4j v2)
│   └── terraform/           # cloud infra, India-region buckets/DB
├── eval/
│   └── golden_set/          # anonymised real cases + expected outputs
├── .env.example
└── README.md
```

---

## 7. Data model (Postgres, core tables)

- `users` (phone, OTP state, consent timestamps)
- `families` / `family_members` (for ParentCare-style profile reuse)
- `policies` (insurer, policy number, start date, porting history, PED disclosures)
- `cases` (status/state-machine stage, rejection category, created_at, insurer)
- `documents` (case_id, type, storage key, rasterized page keys, OCR confidence)
- `extracted_facts` (case_id, JSON blob: dates, amounts, clause refs — source of truth for rules engine)
- `rule_results` (case_id, rule_name, pass/fail, explanation)
- `letters` (case_id, stage [GRO/Bima Bharosa/Ombudsman], draft text, validated bool, sent_at)
- `deadlines` (case_id, type, due_at, reminded_at, status)
- `payments` (case_id, amount, tier, razorpay_ref)
- `grok_usage_log` (case_id, node, model, prompt_tokens, completion_tokens, cost_inr, latency_ms)
- `outcomes` (case_id, result, amount_recovered, reported_at) — feeds eval set

---

## 8. LangGraph state machine — node I/O summary

| Node | Input | Grok call? | Output |
|---|---|---|---|
| INTAKE | raw upload/WhatsApp media | no | stored documents |
| PREPROCESS | documents | no (rasterization only) | page-tagged PNGs |
| CLASSIFY | PNGs | **yes — budget tier, vision** | rejection category + confidence |
| EXTRACT | PNGs + category | **yes — budget tier, vision, structured output** | dates, amounts, clause snippets, insurer |
| RULE_CHECK | extracted facts | no | pass/fail per rule, contestability score |
| EVIDENCE_GAP | facts + rule results | **yes — budget tier** | checklist of missing documents |
| DRAFT | facts + rule results + RAG clauses (not raw docs) | **yes — flagship** | letter text per stage |
| VALIDATE | draft + source docs + facts | no (deterministic string/date check) | pass → next; fail → regen (max 2) → human queue |
| USER_APPROVE | letter | no | user confirms send |
| TRACK/ESCALATE/OMBUDSMAN | deadlines | no | scheduled state transitions |
| OUTCOME | user report | no | eval-set label |

---

## 9. RAG corpus

Static, versioned corpus to embed once and re-embed on circular updates:
- IRDAI Master Circular on Health Insurance (29 May 2024) — full text, chunked by clause.
- Insurance Ombudsman Rules 2017 (as amended).
- 50–100 published Ombudsman award summaries (precedent retrieval), tagged by rejection category and insurer.
- Insurer-specific playbooks (built incrementally from real cases, starting with the top 6 insurers by complaint volume).

Per-case, ephemeral corpus: the user's own policy wording (embedded at intake, deleted per the DPDP retention policy on case close).

---

## 10. WhatsApp + web intake

- Meta Cloud API or a BSP (Gupshup/Interakt) for the WhatsApp Business number; webhook lands in `apps/whatsapp-webhook` → gateway → orchestrator.
- Media (PDF/photo) comes in via WhatsApp media URLs; download, verify mime type, hand to PREPROCESS.
- Web app mirrors the same intake for users who prefer upload over WhatsApp.

---

## 11. Payments & pricing (unchanged from brief)

Free Case Strength report → ₹499 GRO letter + tracking → ₹1,499 full ladder (GRO → Bima Bharosa → Ombudsman + hearing prep + one human review). Razorpay/UPI. No success-fee model until legal review confirms it's permissible.

---

## 12. Security, DPDP, and a Grok-specific risk

- Health data is personal data under DPDP; most obligations phase in by 13 May 2027 — build to that standard from day one regardless (consent notice, purpose limitation, encryption at rest, deletion on case close + retention window, breach runbook, DPA with every vendor).
- **Grok-specific gap vs. the original Gemini-based plan:** Google/Vertex AI has established India-adjacent enterprise data-processing terms; xAI's standard API, as a newer product, needs its current DPA/data-retention/training-opt-out terms checked explicitly before sending real health documents through it. Action item: before beta, get xAI's written confirmation (enterprise terms or API data-usage policy) that prompt/response content is not retained for model training and ask about regional processing options.
- Mitigate in the meantime by minimizing what reaches Grok: send rasterized document images for OCR/extraction (necessary), but for the flagship DRAFT call, send only structured facts — never raw documents — which also keeps prompts in the cheap pricing tier (§3) and limits PII exposure to the minimum needed to write the letter.
- Store raw documents only in India-region encrypted object storage, not in any LLM-vendor-side history.

---

## 13. Unit economics, recomputed for Grok

| Item per case | Assumption | Est. cost |
|---|---|---|
| OCR + classification + extraction (vision) | ~40 page-images + ~15K output tokens, budget-tier model | ~$0.10–0.20 (~₹9–17) |
| Evidence-gap check | ~5K in / 1K out, budget-tier | ~$0.01 (~₹1) |
| Letter drafting (3 letters, structured facts only, flagship) | ~8K in / 6K out total | ~$0.08–0.10 (~₹7–9) |
| Voice intake (optional) | 20 min Sarvam STT + ~5K chars TTS | ~₹25 |
| Storage, WhatsApp, payment fees (~2%) | — | ~₹30–50 |
| **Total variable cost/case** | | **~₹70–100** (vs. ~₹120–140 estimated for the Gemini-based plan) |

Gross margin at the ₹499/₹1,499 tiers stays in the 70–90% range before human review, now with more headroom because Grok's budget tier undercuts Gemini Flash-Lite on the high-volume OCR/extraction calls. Treat this table as directional — re-run it against actual token counts from the first 50 real cases.

---

## 14. 12-week roadmap

| Phase | Weeks | Grok-specific deliverables | Other deliverables (unchanged) |
|---|---|---|---|
| 1. Discovery | 1–3 | Get xAI API key + spend cap; run 10 real rejection letters through raw Grok vision calls to sanity-check OCR quality on Indian insurer formats before committing architecture | Concierge pilot (30 cases), 15 interviews, golden set collection, legal opinion on positioning |
| 2. Product design | 3–4 | Finalize model router config, JSON schemas for Classify/Extract/Draft, two-tier pricing budget per node | MVP scope lock, WhatsApp-first flow, repo scaffold (§6), Postgres schema |
| 3. Development | 5–9 | Build PDF→PNG pipeline, `grok_client.py` wrapper, all LangGraph nodes, token-usage logging | Rules engine, hybrid RAG ingestion, deadline scheduler, Razorpay, OTP auth, admin console |
| 4. Quality & reliability | 9–11 | Grok rate-limit/retry testing, two-tier pricing cost audit against real usage, fallback-to-OCR path testing on bad scans | Golden-set eval, citation validator regen loop, red-team for hallucinated clauses/dates, DPDP consent flows |
| 5. Launch | 11–12+ | Confirm xAI data-retention terms are acceptable before any real case data flows in production | Closed beta, public launch to communities, weekly outcome tracking |

---

## 15. Environment setup

```
# .env.example
XAI_API_KEY=
XAI_BASE_URL=https://api.x.ai/v1
XAI_MODEL_BUDGET=grok-4.3          # verify current slug at build time
XAI_MODEL_FLAGSHIP=grok-4.7        # verify current slug at build time
SARVAM_API_KEY=
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
QDRANT_URL=http://...
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
WHATSAPP_TOKEN=
OBJECT_STORE_BUCKET=                # India region
```

1. Create an xAI account at console.x.ai, generate an API key, set a monthly spend cap.
2. `docker compose -f infra/docker-compose.yml up -d` for Postgres/Redis/Qdrant.
3. `alembic upgrade head` to apply schema.
4. Run `rag/ingest/` scripts once to embed the Master Circular, Ombudsman Rules, and seed awards.
5. Smoke-test: send one real (or sample) rejection letter through PREPROCESS → CLASSIFY → EXTRACT and inspect the structured JSON before building further nodes.

---

## 16. Testing & evaluation

- Golden set: 50–100 anonymised real cases with known outcomes (consented, from the concierge pilot).
- Metrics: citation precision (must be ~100%, it's string-matched), deadline accuracy (100% — deterministic, should never fail), classification F1, human-rated letter quality 1–5.
- Every change to a Grok model slug or prompt re-runs the full golden set before deploying (model drift is a real risk with a vendor that revises models every few months).

---

## 17. Risks specific to this Grok-based build

- **Model churn:** xAI has retired/renamed budget models before (grok-4-fast → newer variants within the same year). The model-router config (§3) exists specifically to absorb this without a code change.
- **PDF handling:** Grok vision takes images only — the PDF→PNG step is a new piece of infrastructure this plan has that a PDF-native provider wouldn't need. Budget real engineering time for it, including edge cases (password-protected PDFs, rotated scans, multi-page TIFFs from some hospital systems).
- **Two-tier pricing cliffs:** sending a full dossier into the flagship model instead of structured facts could silently 5–10x the per-case drafting cost. Enforce the "facts only, not raw docs" rule into DRAFT at the code level (strip/validate payload size before the call), not just as a design intention.
- **Data-retention terms:** confirm in writing before production (§12) — this is the one item that could force a provider swap late if unresolved.
- **No confirmed India-region hosting for xAI today:** factor into the DPDP cross-border-transfer disclosure in the privacy notice.

---

## 18. Immediate next steps

1. Get an xAI API key and run the §15 smoke test against 3–5 real rejection-letter scans to validate OCR/extraction quality before writing any pipeline code — this is the single highest-uncertainty assumption in the whole plan.
2. Scaffold the repo structure in §6 and the Postgres schema in §7.
3. Start the concierge pilot (Phase 1) in parallel — it produces the golden set this whole evaluation strategy depends on.

---

### Sources consulted for Grok specifics
- [xAI model docs](https://docs.x.ai/docs/models)
- [xAI image understanding guide](https://docs.x.ai/docs/guides/image-understanding)
- [Grok 4 Fast pricing — pricepertoken.com](https://pricepertoken.com/pricing-page/model/xai-grok-4-fast)
- [Grok 4 pricing — pricepertoken.com](https://pricepertoken.com/pricing-page/model/xai-grok-4)
- [xAI Grok API Pricing 2026 — opslyft.com](https://www.opslyft.com/blog/ai-grok-api-pricing-2026)
