"""LangGraph state machines wiring the case pipeline (IMPLEMENTATION_PLAN.md section 8).

Split into two graphs, not one, so payment can gate the boundary between them:
- build_preview_graph(): preprocess -> ocr -> classify -> extract -> rule_check ->
  evidence_gap. This is the free "Case Strength" report from the plan's pricing
  model (section 7) -- no LLM drafting happens here, so nothing paid-for is
  given away before a payment is verified.
- build_draft_graph(): draft -> validate, with the retry-then-human-review loop.
  Only invoked from the gateway after a verified Razorpay payment.

fraud_allegation cases never reach extract/draft at all: the plan's guardrail
list requires those go to "consult a lawyer", not an auto-drafted letter.
"""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from services.orchestrator.nodes import classify, draft, evidence_gap, extract, ocr, preprocess, rule_check, validate

MAX_DRAFT_ATTEMPTS = 2


class CaseState(TypedDict, total=False):
    case_id: str
    documents: list[dict]
    classification: dict
    extracted_facts: dict
    rule_results: list[dict]
    contestable: bool
    evidence_gaps: dict
    letters: dict
    validation: dict
    stage: str
    case_status: str


def _draft_stage(state: CaseState) -> CaseState:
    return draft.run(state, state["stage"])


def _validate_stage(state: CaseState) -> CaseState:
    return validate.run(state, state["stage"])


def _flag_fraud_review(state: CaseState) -> CaseState:
    state["case_status"] = "needs_human_review_fraud"
    return state


def _flag_preview_done(state: CaseState) -> CaseState:
    state["case_status"] = "preview_ready"
    return state


def _flag_max_attempts(state: CaseState) -> CaseState:
    state["case_status"] = "needs_human_review_max_attempts"
    return state


def _flag_approved(state: CaseState) -> CaseState:
    state["case_status"] = "drafted"
    return state


def _after_classify(state: CaseState) -> str:
    if state["classification"]["category"] == "fraud_allegation":
        return "fraud_review"
    return "continue"


def _after_validate(state: CaseState) -> str:
    result = state["validation"][state["stage"]]
    if result["passed"]:
        return "approve"
    if result["attempt"] >= MAX_DRAFT_ATTEMPTS:
        return "human_review"
    return "retry_draft"


def build_preview_graph():
    graph = StateGraph(CaseState)
    graph.add_node("preprocess", preprocess.run)
    graph.add_node("ocr", ocr.run)
    graph.add_node("classify", classify.run)
    graph.add_node("extract", extract.run)
    graph.add_node("rule_check", rule_check.run)
    graph.add_node("evidence_gap", evidence_gap.run)
    graph.add_node("flag_fraud_review", _flag_fraud_review)
    graph.add_node("flag_preview_done", _flag_preview_done)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "ocr")
    graph.add_edge("ocr", "classify")
    graph.add_conditional_edges(
        "classify",
        _after_classify,
        {"continue": "extract", "fraud_review": "flag_fraud_review"},
    )
    graph.add_edge("flag_fraud_review", END)
    graph.add_edge("extract", "rule_check")
    graph.add_edge("rule_check", "evidence_gap")
    graph.add_edge("evidence_gap", "flag_preview_done")
    graph.add_edge("flag_preview_done", END)
    return graph.compile()


def build_draft_graph():
    graph = StateGraph(CaseState)
    graph.add_node("draft", _draft_stage)
    graph.add_node("validate", _validate_stage)
    graph.add_node("flag_max_attempts", _flag_max_attempts)
    graph.add_node("flag_approved", _flag_approved)

    graph.set_entry_point("draft")
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges(
        "validate",
        _after_validate,
        {"approve": "flag_approved", "retry_draft": "draft", "human_review": "flag_max_attempts"},
    )
    graph.add_edge("flag_approved", END)
    graph.add_edge("flag_max_attempts", END)
    # TODO: route flag_max_attempts/flag_fraud_review to an actual human-review
    # queue (a DB row + notification), not just a state flag -- no such queue
    # exists yet. TODO: pass a Postgres-backed checkpointer so a case can pause
    # for the 30-day GRO window / 1-year Ombudsman window mid-pipeline, per the
    # architecture diagram in IMPLEMENTATION_PLAN.md section 2.
    return graph.compile()
