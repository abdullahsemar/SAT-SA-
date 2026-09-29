"""Explanation generation for selected portfolio items and overall portfolio summary.

Provides transparent, audit-ready natural language explanations:
- Why each item was chosen (marginal hypothesis coverage, group diversity, efficiency rank).
- Exact source evidence citations (record locator, native ID, SHA-256 hash).
- Remaining uncertainties and boundary caveats.
- What concrete supervisory fact or distinction review could establish.
- Portfolio-level budget utilization, covered vs uncovered hypotheses, and shortfalls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from packages.analytics.selection.candidates import CandidateUnit
from packages.analytics.selection.optimizer import OptimizationResult


class ExplanationGenerator:
    """Generates detailed textual and structured explanations for selected review items."""

    @staticmethod
    def generate_item_explanation(
        item: CandidateUnit,
        rank: int,
        log_entry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Builds an examiner-facing explanation card for a selected candidate item."""
        stratum = item.stratum
        marginal_gain = log_entry.get("marginal_gain", 0.0) if log_entry else 0.0
        efficiency = log_entry.get("marginal_efficiency", 0.0) if log_entry else 0.0

        if stratum == "targeted":
            why_selected = (
                f"Selected at rank #{rank} as a targeted review unit. "
                f"Contributes {marginal_gain:.2f} marginal objective gain "
                f"({efficiency:.3f} gain/minute) across hypotheses: {', '.join(item.hypothesis_links)}."
            )
        elif stratum == "control":
            why_selected = (
                f"Selected at rank #{rank} as an unflagged control sample. "
                f"Drawn deterministically from the unflagged eligible population to audit baseline compliance "
                f"and test for undetected false negatives."
            )
        else:
            why_selected = (
                f"Selected at rank #{rank} as an exploratory unit to inspect boundary conditions "
                f"and secondary indicators."
            )

        citations: List[Dict[str, Any]] = []
        for ref in item.evidence_references:
            citations.append(
                {
                    "source_id": ref.get("source_id", "unknown"),
                    "record_type": ref.get("record_type", "unknown"),
                    "locator": ref.get("locator") or ref.get("row_locator", ""),
                    "native_id": ref.get("native_id", ""),
                    "sha256": ref.get("sha256", ""),
                }
            )

        uncertainties = (
            item.unknowns
            if item.unknowns
            else ["No explicit telemetry omissions recorded; baseline scrutiny applies."]
        )

        return {
            "rank": rank,
            "unit_id": item.unit_id,
            "unit_type": item.unit_type,
            "scope": item.scope,
            "stratum": item.stratum,
            "why_selected": why_selected,
            "marginal_gain": round(marginal_gain, 4),
            "marginal_efficiency": round(efficiency, 4),
            "covered_hypotheses": item.hypothesis_links,
            "estimated_review_minutes": item.estimated_review_minutes,
            "rubric_review_value": item.review_value,
            "citations": citations,
            "uncertainties": uncertainties,
            "what_examiner_could_learn": item.what_examiner_could_learn,
        }

    @staticmethod
    def generate_portfolio_summary(result: OptimizationResult) -> Dict[str, Any]:
        """Builds a human-readable portfolio-level summary."""
        cov = result.coverage_summary
        covered_count = cov.get("distinct_hypotheses_covered_count", 0)
        total_hyp = cov.get("total_hypotheses_count", 0)
        uncovered = cov.get("uncovered_hypotheses", [])

        has_shortfall = any(v > 0 for v in result.shortfalls.values())
        shortfall_msg = (
            f"Quota shortfall detected: {result.shortfalls}. Fewer items returned to prevent synthetic padding."
            if has_shortfall
            else "All requested strata quotas were successfully fulfilled."
        )

        return {
            "total_items": len(result.selected_items),
            "total_review_minutes": result.total_minutes,
            "minute_budget": result.budget_minutes,
            "objective_value": result.objective_value,
            "weights_version": result.weights_version,
            "seed": result.seed,
            "strata_distribution": result.strata_counts,
            "strata_targets": result.strata_targets,
            "shortfalls": result.shortfalls,
            "shortfall_explanation": shortfall_msg,
            "hypotheses_covered_count": covered_count,
            "total_hypotheses_count": total_hyp,
            "covered_hypotheses_list": list(cov.get("covered_hypotheses", {}).keys()),
            "remaining_uncovered_hypotheses": uncovered,
            "groups_covered_count": cov.get("groups_covered_count", 0),
            "limitations_disclosure": result.limitations_disclosure,
        }
