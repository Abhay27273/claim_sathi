"""FastAPI gateway entrypoint. Run with: uvicorn services.gateway.main:app --reload

Every /cases* endpoint requires the X-API-Key header (services/gateway/security.py)
and is rate-limited. Pricing tiers per IMPLEMENTATION_PLAN.md section 7:
  - POST /cases              : free Case Strength report (classify/extract/rule_check/
                                evidence_gap only -- no letter, nothing paid-for given away)
  - POST /cases/{id}/orders  : create a Razorpay order, tier = gro_letter (Rs 499) or
                                full_ladder (Rs 1,499: GRO + Bima Bharosa + Ombudsman)
  - POST /cases/{id}/draft   : verify payment (either tier), draft+validate the GRO letter
  - POST /cases/{id}/escalate: draft Bima Bharosa or Ombudsman -- requires a full_ladder
                                payment already verified for this case (one payment covers
                                all three stages), and the prior stage's letter to exist
                                (can't escalate to Ombudsman before Bima Bharosa, etc.)
"""
import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.gateway import otp, razorpay_client, security, whatsapp
from services.gateway.db import get_connection
from services.orchestrator.graph import build_draft_graph, build_preview_graph
from services.orchestrator.nodes.preprocess import run as preprocess_run
from services.scheduler.deadlines import schedule_gro_deadline, schedule_ombudsman_deadline

logger = logging.getLogger("claimsaathi.gateway")

app = FastAPI(title="ClaimSaathi Gateway")


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace or internal error text to the client -- log it
    server-side with a correlation id instead."""
    error_id = str(uuid.uuid4())
    logger.exception("Unhandled error [%s] on %s %s", error_id, request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error_id": error_id})


STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR", "./var/documents"))
_PREVIEW_GRAPH = build_preview_graph()
_DRAFT_GRAPH = build_draft_graph()

GRO_LETTER_PRICE_PAISE = 49900  # Rs 499
FULL_LADDER_PRICE_PAISE = 149900  # Rs 1,499
TIER_PRICES = {"gro_letter": GRO_LETTER_PRICE_PAISE, "full_ladder": FULL_LADDER_PRICE_PAISE}

STAGE_ORDER = ["gro", "bima_bharosa", "ombudsman"]

RATE_LIMITS = {
    "cases": (10, 3600),
    "orders": (30, 3600),
    "draft": (10, 3600),
    "request_otp": (5, 900),  # 5 per 15 min per phone -- this is what stops SMS-bombing a number
    "verify_otp": (5, 900),  # 5 per 15 min per phone -- stops brute-forcing the 6-digit OTP
}


@app.get("/health")
def health():
    return {"status": "ok"}


# -- Phone-OTP auth --------------------------------------------------------
# Separate from GATEWAY_API_KEY (services/gateway/security.py), which gates
# API access generally. This identifies WHICH user is calling -- not built
# into the rest of the gateway's endpoints yet (those still only check the
# shared API key), but the primitive a frontend would build on.


class OTPRequest(BaseModel):
    phone: str


@app.post("/auth/request-otp")
def request_otp(body: OTPRequest):
    security.enforce_rate_limit(f"ratelimit:request_otp:{body.phone}", *RATE_LIMITS["request_otp"])
    result = otp.request_otp(body.phone)
    return result


class OTPVerify(BaseModel):
    phone: str
    otp: str


@app.post("/auth/verify-otp")
def verify_otp_endpoint(body: OTPVerify):
    security.enforce_rate_limit(f"ratelimit:verify_otp:{body.phone}", *RATE_LIMITS["verify_otp"])
    if not otp.verify_otp(body.phone, body.otp):
        raise HTTPException(400, "Invalid or expired OTP")
    token = otp.create_session(body.phone)
    return {"session_token": token}


def _create_case_from_documents(policy_id: str, document_specs: list[dict]) -> dict:
    """Shared by the HTTP /cases upload endpoint and the WhatsApp webhook --
    both end up with the same shape (policy_id + a list of {doc_type,
    mime_type, data, filename}), just from different intake surfaces."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM policies WHERE id = %s", (policy_id,))
            if cur.fetchone() is None:
                raise HTTPException(404, f"policy {policy_id} not found")

            cur.execute("INSERT INTO cases (policy_id, stage) VALUES (%s, 'intake') RETURNING id", (policy_id,))
            case_id = str(cur.fetchone()["id"])

            case_dir = STORAGE_DIR / case_id
            case_dir.mkdir(parents=True, exist_ok=True)

            documents = []
            for spec in document_specs:
                security.validate_upload(spec["mime_type"], spec["data"])
                dest = security.safe_destination(case_dir, spec["filename"])
                dest.write_bytes(spec["data"])
                cur.execute(
                    "INSERT INTO documents (case_id, type, mime_type, storage_path) VALUES (%s, %s, %s, %s) RETURNING id",
                    (case_id, spec["doc_type"], spec["mime_type"], str(dest)),
                )
                documents.append(
                    {
                        "id": str(cur.fetchone()["id"]),
                        "type": spec["doc_type"],
                        "mime_type": spec["mime_type"],
                        "storage_path": str(dest),
                    }
                )
        conn.commit()

    preprocessed = preprocess_run({"case_id": case_id, "documents": documents})

    with get_connection() as conn:
        with conn.cursor() as cur:
            for doc in preprocessed["documents"]:
                cur.execute(
                    "UPDATE documents SET page_image_paths = %s WHERE id = %s",
                    (json.dumps(doc["page_images"]), doc["id"]),
                )
        conn.commit()

    final_state = _PREVIEW_GRAPH.invoke({"case_id": case_id, "documents": preprocessed["documents"]})

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cases SET stage = %s, rejection_category = %s, contestable = %s WHERE id = %s",
                (
                    final_state.get("case_status", "preview_ready"),
                    final_state.get("classification", {}).get("category"),
                    final_state.get("contestable"),
                    case_id,
                ),
            )
            if final_state.get("extracted_facts"):
                cur.execute(
                    "INSERT INTO extracted_facts (case_id, facts) VALUES (%s, %s)",
                    (case_id, json.dumps(final_state["extracted_facts"])),
                )
            for rule in final_state.get("rule_results", []):
                cur.execute(
                    "INSERT INTO rule_results (case_id, rule_name, passed, explanation) VALUES (%s, %s, %s, %s)",
                    (case_id, rule["name"], rule["passed"], rule["explanation"]),
                )
        conn.commit()

    return {
        "case_id": case_id,
        "case_status": final_state.get("case_status"),
        "classification": final_state.get("classification"),
        "extracted_facts": final_state.get("extracted_facts"),
        "rule_results": final_state.get("rule_results"),
        "evidence_gaps": final_state.get("evidence_gaps"),
        "contestable": final_state.get("contestable"),
    }


@app.post("/cases", dependencies=[Depends(security.require_api_key)])
async def create_case(
    policy_id: str = Form(...),
    doc_types: list[str] = Form(...),
    files: list[UploadFile] = File(...),
):
    """Create a case and run the free preview pipeline. Does not draft a letter."""
    security.enforce_rate_limit(f"ratelimit:cases:{policy_id}", *RATE_LIMITS["cases"])

    if len(files) != len(doc_types):
        raise HTTPException(400, "files and doc_types must be the same length")
    if len(files) > 10:
        raise HTTPException(400, "Too many files in one case (max 10)")

    document_specs = [
        {"doc_type": doc_type, "mime_type": upload.content_type, "data": await upload.read(), "filename": upload.filename}
        for upload, doc_type in zip(files, doc_types)
    ]
    return _create_case_from_documents(policy_id, document_specs)


@app.post("/cases/{case_id}/orders", dependencies=[Depends(security.require_api_key)])
def create_order(case_id: str, tier: str = Form("gro_letter")):
    """Create a Razorpay order. tier is 'gro_letter' (Rs 499, GRO only) or
    'full_ladder' (Rs 1,499, unlocks GRO + Bima Bharosa + Ombudsman for this case)."""
    if tier not in TIER_PRICES:
        raise HTTPException(400, f"tier must be one of {sorted(TIER_PRICES)}")
    security.enforce_rate_limit(f"ratelimit:orders:{case_id}", *RATE_LIMITS["orders"])

    amount = TIER_PRICES[tier]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage FROM cases WHERE id = %s", (case_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"case {case_id} not found")
            if row["stage"] == "needs_human_review_fraud":
                raise HTTPException(403, "This case was routed to human/legal review and cannot be auto-drafted.")

            order = razorpay_client.create_order(amount, receipt=f"case-{case_id}-{tier}")
            cur.execute(
                "INSERT INTO payments (case_id, amount_inr, tier, razorpay_ref) VALUES (%s, %s, %s, %s)",
                (case_id, amount / 100, tier, order["id"]),
            )
        conn.commit()

    return {"order_id": order["id"], "amount_paise": amount, "tier": tier, "key_id": os.environ["RAZORPAY_KEY_ID"]}


class PaymentConfirmation(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


def _verify_and_consume_payment(case_id: str, body: PaymentConfirmation) -> dict:
    """Shared by /draft. Three independent checks, each closing a different
    attack: the order belongs to this case (stops reusing case A's payment for
    case B), the signature is valid (stops a forged payment_id), and Razorpay
    confirms the payment was actually captured for the tier's exact amount
    (stops a created-but-unpaid order being treated as paid)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tier, razorpay_ref, paid_at FROM payments WHERE case_id = %s AND razorpay_ref = %s",
                (case_id, body.razorpay_order_id),
            )
            payment_row = cur.fetchone()
    if payment_row is None:
        raise HTTPException(400, "This order_id does not belong to this case")
    if payment_row["paid_at"] is not None:
        raise HTTPException(409, "This order has already been used")

    if not razorpay_client.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(400, "Invalid payment signature")

    payment = razorpay_client.fetch_payment(body.razorpay_payment_id)
    if payment.get("status") != "captured" or payment.get("order_id") != body.razorpay_order_id:
        raise HTTPException(402, f"Payment not captured (status={payment.get('status')!r})")
    if payment.get("amount") != TIER_PRICES[payment_row["tier"]]:
        raise HTTPException(402, f"Payment amount mismatch: {payment.get('amount')}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE payments SET paid_at = now() WHERE id = %s", (payment_row["id"],))
        conn.commit()
    return payment_row


def _load_case_context(case_id: str) -> tuple[dict, dict, list]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage, rejection_category FROM cases WHERE id = %s", (case_id,))
            case_row = cur.fetchone()
            if case_row is None:
                raise HTTPException(404, f"case {case_id} not found")
            cur.execute("SELECT facts FROM extracted_facts WHERE case_id = %s", (case_id,))
            facts_row = cur.fetchone()
            cur.execute("SELECT rule_name, passed, explanation FROM rule_results WHERE case_id = %s", (case_id,))
            rule_rows = cur.fetchall()
    if facts_row is None:
        raise HTTPException(409, "Case has no extracted facts yet -- run POST /cases first")
    return case_row, facts_row, rule_rows


def _run_draft_stage(case_id: str, stage: str, case_row: dict, facts_row: dict, rule_rows: list) -> dict:
    final_state = _DRAFT_GRAPH.invoke(
        {
            "case_id": case_id,
            "stage": stage,
            "classification": {"category": case_row["rejection_category"]},
            "extracted_facts": facts_row["facts"],
            "rule_results": [dict(r) for r in rule_rows],
            "letters": {},
            "validation": {},
        }
    )
    validation = final_state.get("validation", {}).get(stage, {})
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE cases SET stage = %s WHERE id = %s", (final_state.get("case_status"), case_id))
            cur.execute(
                "INSERT INTO letters (case_id, stage, draft_text, validated, validation_attempt) VALUES (%s, %s, %s, %s, %s)",
                (
                    case_id,
                    stage,
                    final_state.get("letters", {}).get(stage),
                    validation.get("passed", False),
                    validation.get("attempt", 0),
                ),
            )
        conn.commit()
    return final_state


@app.post("/cases/{case_id}/draft", dependencies=[Depends(security.require_api_key)])
def draft_letter(case_id: str, body: PaymentConfirmation):
    """Verify payment (either tier unlocks GRO), then draft+validate the GRO letter."""
    security.enforce_rate_limit(f"ratelimit:draft:{case_id}", *RATE_LIMITS["draft"])
    case_row, facts_row, rule_rows = _load_case_context(case_id)
    if case_row["stage"] == "needs_human_review_fraud":
        raise HTTPException(403, "This case was routed to human/legal review and cannot be auto-drafted.")

    _verify_and_consume_payment(case_id, body)
    final_state = _run_draft_stage(case_id, "gro", case_row, facts_row, rule_rows)

    if final_state.get("case_status") == "drafted":
        schedule_gro_deadline(case_id)
        rejection_date = facts_row["facts"].get("rejection_date")
        if rejection_date:
            schedule_ombudsman_deadline(case_id, rejection_date)

    return {
        "case_id": case_id,
        "case_status": final_state.get("case_status"),
        "letter_gro": final_state.get("letters", {}).get("gro"),
        "validation": final_state.get("validation"),
    }


class EscalateRequest(BaseModel):
    stage: str  # "bima_bharosa" or "ombudsman"


@app.post("/cases/{case_id}/escalate", dependencies=[Depends(security.require_api_key)])
def escalate_case(case_id: str, body: EscalateRequest):
    """Draft the Bima Bharosa or Ombudsman letter. Requires a full_ladder payment
    already verified for this case (one payment covers all three stages -- no new
    Razorpay round-trip needed here), and requires the prior stage in STAGE_ORDER
    to have an existing letter (can't jump straight to Ombudsman)."""
    if body.stage not in ("bima_bharosa", "ombudsman"):
        raise HTTPException(400, "stage must be 'bima_bharosa' or 'ombudsman'")
    security.enforce_rate_limit(f"ratelimit:draft:{case_id}", *RATE_LIMITS["draft"])

    case_row, facts_row, rule_rows = _load_case_context(case_id)
    if case_row["stage"] == "needs_human_review_fraud":
        raise HTTPException(403, "This case was routed to human/legal review and cannot be auto-drafted.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM payments WHERE case_id = %s AND tier = 'full_ladder' AND paid_at IS NOT NULL",
                (case_id,),
            )
            if cur.fetchone() is None:
                raise HTTPException(402, "Escalation requires the full-ladder tier (Rs 1,499) paid for this case")

            prior_stage = STAGE_ORDER[STAGE_ORDER.index(body.stage) - 1]
            cur.execute("SELECT 1 FROM letters WHERE case_id = %s AND stage = %s", (case_id, prior_stage))
            if cur.fetchone() is None:
                raise HTTPException(409, f"Cannot escalate to {body.stage} before the {prior_stage} letter exists")

    final_state = _run_draft_stage(case_id, body.stage, case_row, facts_row, rule_rows)

    return {
        "case_id": case_id,
        "stage": body.stage,
        "case_status": final_state.get("case_status"),
        "letter": final_state.get("letters", {}).get(body.stage),
        "validation": final_state.get("validation"),
    }


# -- Human review queue --------------------------------------------------
# A case lands here via graph.py's case_status flags (needs_human_review_fraud,
# needs_human_review_max_attempts). resolved_by is free text for now -- there's
# no reviewer-identity auth yet, just the shared GATEWAY_API_KEY everyone uses.
# Resolving a case records the decision; it does NOT automatically resume the
# pipeline (a fraud-flagged case was never extracted/drafted at all -- the
# plan's guardrail is "send it to a lawyer", not "let the model try again").

REVIEW_STATUSES = ["needs_human_review_fraud", "needs_human_review_max_attempts"]


@app.get("/review-queue", dependencies=[Depends(security.require_api_key)])
def list_review_queue():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id AS case_id, c.stage, c.rejection_category, c.created_at
                FROM cases c
                WHERE c.stage = ANY(%s)
                ORDER BY c.created_at ASC
                """,
                (REVIEW_STATUSES,),
            )
            rows = cur.fetchall()
    return {"cases": [dict(r) for r in rows]}


class ReviewResolution(BaseModel):
    action: str  # "cleared_for_draft" | "rejected" | "escalated_to_lawyer"
    note: str = ""
    resolved_by: str = ""


@app.post("/review-queue/{case_id}/resolve", dependencies=[Depends(security.require_api_key)])
def resolve_review(case_id: str, body: ReviewResolution):
    if body.action not in ("cleared_for_draft", "rejected", "escalated_to_lawyer"):
        raise HTTPException(400, "action must be one of: cleared_for_draft, rejected, escalated_to_lawyer")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stage FROM cases WHERE id = %s", (case_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"case {case_id} not found")
            if row["stage"] not in REVIEW_STATUSES:
                raise HTTPException(409, f"Case is not in the review queue (stage={row['stage']!r})")

            cur.execute(
                "INSERT INTO human_review_notes (case_id, note, action, resolved_by) VALUES (%s, %s, %s, %s)",
                (case_id, body.note, body.action, body.resolved_by),
            )
            cur.execute("UPDATE cases SET stage = %s WHERE id = %s", (f"human_review_{body.action}", case_id))
        conn.commit()

    return {"case_id": case_id, "resolved_action": body.action}


# -- WhatsApp webhook -------------------------------------------------------
# No X-API-Key here -- Meta calls this directly, authenticated instead by
# WHATSAPP_VERIFY_TOKEN (the one-time GET handshake) and the per-request
# X-Hub-Signature-256 HMAC (every POST). Untested beyond that: downloading
# real media and sending real replies both need a WHATSAPP_TOKEN that doesn't
# exist yet (no WhatsApp Business Account set up).
#
# Known v1 simplification: each incoming document is processed as its own
# case immediately -- there's no accumulation of "rejection letter THEN
# policy wording" across separate messages yet. A real conversation flow
# (wait for more documents, or a "done" command) is a reasonable next step,
# not built here.


@app.get("/webhook/whatsapp")
def whatsapp_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    try:
        challenge = whatsapp.verify_webhook_challenge(hub_mode, hub_verify_token, hub_challenge)
    except ValueError:
        raise HTTPException(403, "Verification failed")
    return Response(content=challenge, media_type="text/plain")


def _find_or_create_policy_for_phone(phone: str) -> str:
    """WhatsApp users arrive with no prior registration -- auto-provision a
    minimal user/family/family_member/policy shell on first contact and reuse
    it on later contacts from the same number. coverage_start_date is a
    placeholder (today's date): EXTRACT derives the real policy_start_date
    independently into extracted_facts, which is what rule_check.py actually
    reads for moratorium/waiting-period math -- this DB column isn't on that
    path, it's just a profile record for future features (ParentCare Vault)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE phone = %s", (phone,))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO users (phone) VALUES (%s) RETURNING id", (phone,))
                row = cur.fetchone()
            user_id = row["id"]

            cur.execute("SELECT id FROM families WHERE owner_user_id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO families (owner_user_id) VALUES (%s) RETURNING id", (user_id,))
                row = cur.fetchone()
            family_id = row["id"]

            cur.execute("SELECT id FROM family_members WHERE family_id = %s LIMIT 1", (family_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO family_members (family_id, name, relationship) VALUES (%s, 'Self', 'self') RETURNING id",
                    (family_id,),
                )
                row = cur.fetchone()
            member_id = row["id"]

            cur.execute("SELECT id FROM policies WHERE family_member_id = %s ORDER BY created_at DESC LIMIT 1", (member_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO policies (family_member_id, insurer_name, coverage_start_date) "
                    "VALUES (%s, 'Unknown (pending extraction)', CURRENT_DATE) RETURNING id",
                    (member_id,),
                )
                row = cur.fetchone()
            policy_id = str(row["id"])
        conn.commit()
    return policy_id


@app.post("/webhook/whatsapp")
async def whatsapp_receive(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not whatsapp.verify_signature(raw_body, signature):
        raise HTTPException(401, "Invalid webhook signature")

    payload = await request.json()
    message = whatsapp.parse_incoming_message(payload)
    if message is None:
        return {"status": "ignored"}

    policy_id = _find_or_create_policy_for_phone(message["from_phone"])
    security.enforce_rate_limit(f"ratelimit:cases:{policy_id}", *RATE_LIMITS["cases"])

    data, mime_type = whatsapp.download_media(message["media_id"])
    doc_type = "rejection_letter" if "reject" in message["caption"].lower() else "policy_wording"
    result = _create_case_from_documents(
        policy_id,
        [{"doc_type": doc_type, "mime_type": mime_type, "data": data, "filename": f"{message['media_id']}"}],
    )

    reply = (
        f"Got it! Category: {result['classification']['category'] if result['classification'] else 'unclear'}. "
        f"{'This looks contestable.' if result['contestable'] else 'This may not be easily contestable.'} "
        "Reply with your policy wording document too for a fuller report."
    )
    whatsapp.send_text_message(message["from_phone"], reply)
    return {"status": "processed", "case_id": result["case_id"]}
