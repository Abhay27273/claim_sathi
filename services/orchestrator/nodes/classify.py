"""CLASSIFY node: identify the rejection-reason category from the rejection
letter's OCR'd text, via Groq's budget-tier text model.

Pivoted from the original vision-based design (IMPLEMENTATION_PLAN.md section 3)
on 2026-11-17 -- no vision model is available on Groq's self-serve API. The OCR
node (ocr.py, Tesseract) now does the reading; this reasons over the resulting
text instead of page images.

temperature=0 because a real test run (2026-11-17) produced different
cited_clause_numbers extraction across two runs of the IDENTICAL input --
sampling variance on what must be a deterministic extraction task, not
creative writing. Found by actually re-running the pipeline twice, not assumed."""
import json

from services.orchestrator import usage_log
from services.orchestrator.groq_client import call
from services.orchestrator.prompt_guard import UNTRUSTED_CONTENT_SYSTEM_PROMPT, wrap_untrusted

CATEGORIES = [
    "pre_existing_disease_non_disclosure",
    "waiting_period",
    "not_medically_necessary",
    "room_rent_proportionate_deduction",
    "consumables_non_payables",
    "missing_documents_query",
    "policy_exclusion_clause",
    "fraud_allegation",
]

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "rejection_classification",
        "schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "confidence": {"type": "number"},
                "evidence_snippet": {"type": "string"},
            },
            "required": ["category", "confidence"],
        },
    },
}


def document_text(doc: dict) -> str:
    return "\n\n".join(f"--- Page {i + 1} ---\n{text}" for i, text in enumerate(doc["page_text"]))


def run(state: dict) -> dict:
    rejection_doc = next(d for d in state["documents"] if d["type"] == "rejection_letter")
    messages = [
        {"role": "system", "content": UNTRUSTED_CONTENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Classify this health-insurance rejection letter into exactly one category "
                "from the allowed list, and quote the sentence that supports your answer.\n\n"
                f"{wrap_untrusted('rejection_letter', document_text(rejection_doc))}"
            ),
        },
    ]
    response, usage = call("classify", messages, response_format=RESPONSE_SCHEMA, temperature=0)
    usage_log.record(state["case_id"], usage)
    state["classification"] = json.loads(response.choices[0].message.content)
    return state
