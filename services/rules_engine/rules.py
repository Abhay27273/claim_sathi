"""Deterministic rule checks against IRDAI's Master Circular on Health Insurance
(29 May 2024) and the Insurance Ombudsman Rules 2017. Pure Python -- no LLM involved,
because an incorrect date or threshold here can cost a user their claim."""
from dataclasses import dataclass
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

MORATORIUM_MONTHS = 60


@dataclass
class RuleResult:
    name: str
    passed: bool
    explanation: str


def _parse_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def check_moratorium(policy_start_date: str, claim_date: str, ported_continuous_coverage: bool) -> RuleResult:
    """After 60 months of continuous (including ported) coverage, a claim is not
    contestable on non-disclosure/misrepresentation grounds except established fraud."""
    start = _parse_date(policy_start_date)
    claim = _parse_date(claim_date)
    moratorium_date = start + relativedelta(months=MORATORIUM_MONTHS)
    within_moratorium = claim < moratorium_date
    return RuleResult(
        name="moratorium",
        passed=not within_moratorium,
        explanation=(
            f"Claim date {claim} is {'before' if within_moratorium else 'after'} "
            f"the moratorium date {moratorium_date} "
            f"({'with' if ported_continuous_coverage else 'without'} ported continuity credit)."
        ),
    )


def check_waiting_period(policy_start_date: str, claim_date: str, condition_waiting_period_months: int) -> RuleResult:
    """Checks whether the claim date falls inside the policy's stated waiting period
    for the claimed condition. `condition_waiting_period_months` comes from the
    policy wording, not a universal constant -- it varies by insurer and condition."""
    start = _parse_date(policy_start_date)
    claim = _parse_date(claim_date)
    waiting_period_ends = start + relativedelta(months=condition_waiting_period_months)
    within_waiting_period = claim < waiting_period_ends
    return RuleResult(
        name="waiting_period",
        passed=not within_waiting_period,
        explanation=f"Claim date {claim} vs waiting-period end {waiting_period_ends}.",
    )


def check_crc_approval_required(rejection_category: str) -> RuleResult:
    """No claim may be repudiated without Claims Review Committee / PMC approval.
    This only flags the requirement -- confirming the insurer actually obtained it
    needs evidence requested from the user via EVIDENCE_GAP."""
    return RuleResult(
        name="crc_approval_required",
        passed=False,
        explanation="Insurer must prove CRC/PMC approval was obtained before this repudiation.",
    )


def check_specific_clause_cited(cited_clause_numbers: list[str]) -> RuleResult:
    """The rejection letter must reference the specific policy clause relied on,
    not a generic exclusion -- a bare rejection is itself a procedural defect."""
    has_citation = bool(cited_clause_numbers)
    return RuleResult(
        name="specific_clause_cited",
        passed=has_citation,
        explanation=(
            f"Insurer cited clause(s): {cited_clause_numbers}"
            if has_citation
            else "No specific clause number found in the rejection letter."
        ),
    )


def check_cashless_tat_breach(requested_at: str, responded_at: str, is_discharge: bool) -> RuleResult:
    """Cashless authorisation must be decided within 1 hour; final discharge
    authorisation within 3 hours."""
    requested = datetime.fromisoformat(requested_at)
    responded = datetime.fromisoformat(responded_at)
    limit_hours = 3 if is_discharge else 1
    elapsed_hours = (responded - requested).total_seconds() / 3600
    breached = elapsed_hours > limit_hours
    return RuleResult(
        name="cashless_tat_breach",
        passed=not breached,
        explanation=f"Took {elapsed_hours:.1f}h against a {limit_hours}h limit.",
    )
