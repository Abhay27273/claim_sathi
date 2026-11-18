"""DRAFT node: write the stage-appropriate letter from structured facts only -- never
raw documents. This is a deliberate cost and pricing-tier control: see
IMPLEMENTATION_PLAN.md section 3 on Grok's two-tier flagship pricing, and section 12
on minimizing what reaches the LLM vendor.

JURISDICTION_ANCHOR exists because a real test run (2026-11-17, no jurisdiction
instruction) produced a letter quoting amounts in GBP ("£0") and referencing the
UK's "Financial Ombudsman Service" -- gpt-oss-120b's training data defaulting to
generic/UK patterns with nothing in the prompt to anchor it to India. This is a
correctness bug for a product whose entire value proposition is India-specific
regulatory accuracy, not a cosmetic one.

REGULATORY_CONTEXT comes from rag/retrieval.py -- real text extracted from the
actual IRDAI Master Circular (29 May 2024) and Insurance Ombudsman Rules 2017
PDFs, not the model's training-data memory of them. This is also how "PMC" and
"CRC" got correctly resolved: the circular defines PMC as "Product Management
Committee" and CRC as its three-member sub-group -- previously unknown (the
model had guessed a wrong expansion in an earlier test), now grounded in the
primary source instead of guessed.

DISCLAIMER is appended deterministically in code, not left to the model to
remember to include -- IMPLEMENTATION_PLAN.md section 4 ("Guardrails") requires
every output be labeled self-help drafting, not legal advice; that requirement
shouldn't depend on an LLM reliably following an instruction on every call.

fraud_allegation cases never reach this node -- graph.py routes them to
needs_human_review before DRAFT, per the same guardrail list ("detect
fraud-allegation cases and send them to consult a lawyer")."""
from services.orchestrator import usage_log
from services.orchestrator.groq_client import call
from services.orchestrator.prompt_guard import UNTRUSTED_CONTENT_SYSTEM_PROMPT

JURISDICTION_ANCHOR = (
    "This is for an Indian health insurance policyholder under IRDAI's regulatory "
    "framework. All amounts are in Indian Rupees (INR, Rs. or ₹) -- never GBP/USD/other "
    "currency symbols. Use Indian terminology and bodies only: Grievance Redressal "
    "Officer, IRDAI (Insurance Regulatory and Development Authority of India), the "
    "Insurance Ombudsman (per the Insurance Ombudsman Rules 2017), and Bima Bharosa. "
    "Never reference non-Indian regulators or schemes (e.g. the UK's Financial "
    "Ombudsman Service, FCA, or any US body)."
)

STAGE_PROMPTS = {
    "gro": "Draft a formal grievance-officer complaint letter.",
    "bima_bharosa": "Draft a Bima Bharosa escalation referencing the unresolved GRO complaint.",
    "ombudsman": "Draft an Insurance Ombudsman complaint under the Insurance Ombudsman Rules 2017.",
}

DISCLAIMER = (
    "\n\n---\n"
    "*This letter was drafted by ClaimSaathi, an AI-assisted self-help tool. "
    "It is not legal advice and ClaimSaathi is not a law firm. Review it "
    "carefully, fill in the bracketed personal details, and consult a licensed "
    "advocate before relying on it for a dispute above small amounts or "
    "involving an allegation of fraud.*"
)

SOURCE_LABELS = {
    "irdai_master_circular_health_2024": "IRDAI Master Circular on Health Insurance Business (29 May 2024)",
    "insurance_ombudsman_rules_2017": "Insurance Ombudsman Rules 2017 (as amended)",
}


def _retrieval_query(state: dict) -> str:
    rule_summaries = " ".join(r["explanation"] for r in state.get("rule_results", []))
    return f"{state['classification']['category']} {rule_summaries}"


def _regulatory_context(state: dict) -> str:
    # Imported lazily so a Qdrant/fastembed hiccup degrades to "no retrieved
    # context" rather than crashing drafting entirely -- retrieval is a quality
    # enhancement here, not a hard dependency the whole letter should fail without.
    try:
        from rag.retrieval import retrieve

        hits = retrieve(_retrieval_query(state), top_k=3)
    except Exception:
        return ""
    if not hits:
        return ""
    blocks = [f"[{SOURCE_LABELS.get(h['source'], h['source'])}]\n{h['text']}" for h in hits]
    return (
        "\n\nRelevant regulatory text, retrieved from the actual IRDAI Master Circular and "
        "Insurance Ombudsman Rules 2017 (quote or paraphrase this when it supports the "
        "policyholder's case; cite the source document by the name given in brackets; do not "
        "quote anything from here that isn't actually relevant to this case):\n\n"
        + "\n\n".join(blocks)
    )


def run(state: dict, stage: str) -> dict:
    prompt = (
        f"{JURISDICTION_ANCHOR}\n\n"
        f"{STAGE_PROMPTS[stage]}\n"
        f"Facts: {state['extracted_facts']}\n"
        f"Rule violations to cite: {state['rule_results']}\n"
        f"Classification: {state['classification']['category']}\n"
        "Quote policy-specific clauses (e.g. 'Clause 4.2') only from the facts given above -- "
        "never invent a policy clause number. "
        f"{_regulatory_context(state)}\n\n"
        "If an amount is missing or zero in the facts, do not state a currency figure -- "
        "say the claimed/approved amount is not on record rather than writing a 0 value. "
        "Never expand an abbreviation (e.g. CRC, PMC, IRDAI, TAT) into a full name unless "
        "that full name is given to you explicitly in the facts or regulatory text above -- "
        "if you don't know what it stands for, use the abbreviation alone rather than guessing. "
        "Write this as self-help drafting for the policyholder to review and send themselves, "
        "not as legal advice -- do not claim to be a lawyer or represent the policyholder."
    )
    messages = [
        {"role": "system", "content": UNTRUSTED_CONTENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    response, usage = call("draft", messages)
    usage_log.record(state["case_id"], usage)
    state.setdefault("letters", {})[stage] = response.choices[0].message.content + DISCLAIMER
    return state
