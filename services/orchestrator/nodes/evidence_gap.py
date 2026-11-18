"""EVIDENCE_GAP node: list the specific documents still needed to support the complaint,
via Groq's budget-tier model."""
import json

from services.orchestrator import usage_log
from services.orchestrator.groq_client import call

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "evidence_gaps",
        "schema": {
            "type": "object",
            "properties": {
                "missing_documents": {"type": "array", "items": {"type": "string"}},
                "reasoning": {"type": "string"},
            },
            "required": ["missing_documents"],
        },
    },
}


def run(state: dict) -> dict:
    messages = [
        {
            "role": "user",
            "content": (
                f"Rejection category: {state['classification']['category']}\n"
                f"Rule check results: {state['rule_results']}\n"
                f"Extracted facts: {state['extracted_facts']}\n"
                "List the specific documents still needed to contest this rejection."
            ),
        }
    ]
    response, usage = call("evidence_gap", messages, response_format=RESPONSE_SCHEMA)
    usage_log.record(state["case_id"], usage)
    # `create()` with a response_format dict returns JSON text in .content, not a
    # parsed object -- .parsed only exists via the SDK's beta .parse() helper.
    state["evidence_gaps"] = json.loads(response.choices[0].message.content)
    return state
