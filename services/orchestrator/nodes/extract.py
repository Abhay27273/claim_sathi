"""EXTRACT node: pull the structured facts (dates, amounts, clause text, insurer) that
the deterministic rules engine needs, from OCR'd text. Facts only -- the LLM never
does date arithmetic.

Pivoted from vision to OCR'd text on 2026-11-17 -- see classify.py for why.
temperature=0 for the same reason documented there."""
import json

from services.orchestrator import usage_log
from services.orchestrator.groq_client import call
from services.orchestrator.nodes.classify import document_text
from services.orchestrator.prompt_guard import UNTRUSTED_CONTENT_SYSTEM_PROMPT, wrap_untrusted

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_facts",
        "schema": {
            "type": "object",
            "properties": {
                "insurer_name": {"type": "string"},
                "policy_start_date": {"type": "string", "format": "date"},
                "claim_date": {"type": "string", "format": "date"},
                "rejection_date": {"type": "string", "format": "date"},
                "ported_continuous_coverage": {"type": "boolean"},
                "cited_clause_numbers": {"type": "array", "items": {"type": "string"}},
                "cited_clause_text": {"type": "array", "items": {"type": "string"}},
                "claimed_amount": {"type": "number"},
                "approved_amount": {"type": "number"},
            },
            "required": ["insurer_name", "policy_start_date", "claim_date", "rejection_date"],
        },
    },
}


def run(state: dict) -> dict:
    combined_text = "\n\n".join(
        wrap_untrusted(doc["type"], document_text(doc)) for doc in state["documents"]
    )
    messages = [
        {"role": "system", "content": UNTRUSTED_CONTENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Extract these fields from the attached policy wording and rejection letter text. "
                "Copy every date and amount exactly as written in the source -- do not infer or "
                "calculate. Dates must be normalized to YYYY-MM-DD. If a field isn't present in "
                "the source, omit it rather than guessing a value.\n\n"
                f"{combined_text}"
            ),
        },
    ]
    response, usage = call("extract", messages, response_format=RESPONSE_SCHEMA, temperature=0)
    usage_log.record(state["case_id"], usage)
    state["extracted_facts"] = json.loads(response.choices[0].message.content)
    return state
