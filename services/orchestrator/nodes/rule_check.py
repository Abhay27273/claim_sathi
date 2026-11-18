"""RULE_CHECK node: run the deterministic rules engine against extracted facts. No LLM call --
dates and legal thresholds must never depend on a model getting arithmetic right.

Never bracket-index into `facts` for an optional real-world value -- a real test
(2026-11-17, a case missing the policy wording document) showed EXTRACT's JSON
schema "required" list is not a hard guarantee the field actually comes back;
when it doesn't, the old `facts["policy_start_date"]` crashed the whole request
with an unhandled 500 instead of telling the user what's missing. A policyholder
forgetting to upload one document is a completely ordinary case to handle, not
an exceptional one."""
from services.rules_engine import rules


def run(state: dict) -> dict:
    facts = state["extracted_facts"]
    results = []

    if facts.get("policy_start_date") and facts.get("claim_date"):
        results.append(
            rules.check_moratorium(
                facts["policy_start_date"], facts["claim_date"], facts.get("ported_continuous_coverage", False)
            )
        )
    else:
        results.append(
            rules.RuleResult(
                name="moratorium",
                passed=False,
                explanation=(
                    "Cannot evaluate -- policy_start_date and/or claim_date were not found in the "
                    "submitted documents. Upload the policy schedule/wording showing the policy "
                    "start date, and make sure the claim date is visible in the rejection letter."
                ),
            )
        )

    results.append(rules.check_crc_approval_required(state["classification"]["category"]))
    results.append(rules.check_specific_clause_cited(facts.get("cited_clause_numbers", [])))

    state["rule_results"] = [r.__dict__ for r in results]
    state["contestable"] = any(not r.passed for r in results)
    return state
