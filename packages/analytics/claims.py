"""KPI reconciliation and bounded uncertainty claims engine.

Reconciles self-reported CSE claims (e.g., SLA compliance percentage) against
reconstructed evidence with strict deduplication and bounded uncertainty:
- Lower bound: y / n (where y is verified compliant, n is total population)
- Upper bound: (y + u) / n (where u is unknown/unobserved/indeterminate outcomes)
- Strict distinct-case deduplication so duplicate escalation or alert records
  cannot inflate the numerator or distort the denominator.
- Explicit disproof logic: claim C is contradicted if C > upper_bound or C < lower_bound.
"""

from __future__ import annotations

from typing import Optional, Set

from pydantic import BaseModel


class ReconciliationInterval(BaseModel):
    total_population: int
    verified_compliant: int
    verified_non_compliant: int
    unknown_outcomes: int
    lower_bound_pct: float
    upper_bound_pct: float
    claimed_pct: Optional[float] = None
    is_contradicted: bool = False
    evidence_state: str  # "supported", "contradictory", "insufficient_evidence"
    explanation: str


class ClaimReconciler:
    """Computes bounded uncertainty intervals for self-reported operational claims."""

    @staticmethod
    def evaluate_sla_claim(
        claimed_pct: float,
        compliant_case_ids: Set[str],
        non_compliant_case_ids: Set[str],
        unknown_case_ids: Set[str],
        is_denominator_complete: bool = True,
    ) -> ReconciliationInterval:
        """Evaluates an SLA compliance claim against distinct deduplicated case sets."""
        if not is_denominator_complete:
            return ReconciliationInterval(
                total_population=0,
                verified_compliant=0,
                verified_non_compliant=0,
                unknown_outcomes=0,
                lower_bound_pct=0.0,
                upper_bound_pct=0.0,
                claimed_pct=claimed_pct,
                is_contradicted=False,
                evidence_state="insufficient_evidence",
                explanation="Eligible population denominator is incomplete or unknown; full-population compliance rate cannot be calculated.",
            )

        # Ensure disjoint sets by prioritizing non-compliant, then unknown, then compliant
        all_cases = set(compliant_case_ids | non_compliant_case_ids | unknown_case_ids)
        total_n = len(all_cases)

        if total_n == 0:
            return ReconciliationInterval(
                total_population=0,
                verified_compliant=0,
                verified_non_compliant=0,
                unknown_outcomes=0,
                lower_bound_pct=0.0,
                upper_bound_pct=0.0,
                claimed_pct=claimed_pct,
                is_contradicted=False,
                evidence_state="insufficient_evidence",
                explanation="No relevant cases were found in the submission window to reconcile this claim.",
            )

        y = len(compliant_case_ids - non_compliant_case_ids - unknown_case_ids)
        non_comp = len(non_compliant_case_ids)
        u = len(unknown_case_ids - non_compliant_case_ids)

        lower_bound = round((y / total_n) * 100.0, 2)
        upper_bound = round(((y + u) / total_n) * 100.0, 2)

        # Disproof logic:
        # A contradiction requires the valid upper bound to be strictly below the claimed rate,
        # accounting for documented rounding.
        if claimed_pct > upper_bound:
            is_contradicted = True
            evidence_state = "contradictory"
            explanation = (
                f"Claimed SLA of {claimed_pct:.1f}% is contradicted by reconstructed evidence: "
                f"{non_comp} distinct cases failed policy SLA. "
                f"Maximum achievable compliance is {upper_bound:.1f}% (interval [{lower_bound:.1f}%, {upper_bound:.1f}%])."
            )
        elif lower_bound >= claimed_pct:
            # Verified compliant cases alone guarantee at least the claimed compliance rate
            is_contradicted = False
            evidence_state = "supported"
            explanation = (
                f"Claimed SLA of {claimed_pct:.1f}% is supported by reconstructed evidence: "
                f"verified compliance lower bound of {lower_bound:.1f}% meets or exceeds claimed rate "
                f"(interval [{lower_bound:.1f}%, {upper_bound:.1f}%] over {total_n} distinct cases)."
            )
        elif u > 0 and (lower_bound < claimed_pct <= upper_bound):
            # Claim falls inside uncertainty interval, but interval contains unknowns
            is_contradicted = False
            evidence_state = "insufficient_evidence"
            explanation = (
                f"Claimed SLA of {claimed_pct:.1f}% falls within uncertainty interval "
                f"[{lower_bound:.1f}%, {upper_bound:.1f}%] due to {u} cases with unknown/missing outcome evidence. "
                f"The claim cannot be confirmed or disproved without missing records."
            )
        else:
            # Fully known population (u == 0) and claimed_pct <= upper_bound (which equals lower_bound)
            is_contradicted = False
            evidence_state = "supported"
            explanation = (
                f"Claimed SLA of {claimed_pct:.1f}% is supported by reconstructed evidence: "
                f"{y} of {total_n} distinct cases verified compliant "
                f"(interval [{lower_bound:.1f}%, {upper_bound:.1f}%])."
            )

        return ReconciliationInterval(
            total_population=total_n,
            verified_compliant=y,
            verified_non_compliant=non_comp,
            unknown_outcomes=u,
            lower_bound_pct=lower_bound,
            upper_bound_pct=upper_bound,
            claimed_pct=claimed_pct,
            is_contradicted=is_contradicted,
            evidence_state=evidence_state,
            explanation=explanation,
        )
