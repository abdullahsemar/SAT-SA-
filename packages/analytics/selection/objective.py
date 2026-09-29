"""Submodular diminishing-returns objective function for portfolio selection.

Computes:
  F(S) = alpha * sum_h(weight_h * min(1, sum_{i in S} coverage_i_h))
       + beta  * sum_g(weight_g * min(1, selected_count_in_group_g))
       + gamma * sum_{i in S}(review_value_i)

Invariants:
- Versioned nonnegative weights with documented semantics.
- Values represent an examiner-review rubric, NOT calibrated probabilities or SOC risk scores.
- Alpha rewards covering distinct supervisory hypotheses (diminishing return once fully covered).
- Beta rewards group diversity across dimensions (asset, category, period).
- Gamma rewards base examiner review value (severity / informational priority).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from packages.analytics.selection.candidates import CandidateUnit


@dataclass(frozen=True)
class ObjectiveWeights:
    version: str = "v1.0"
    alpha: float = 2.0  # Weight for hypothesis coverage term
    beta: float = 1.0  # Weight for group diversity term
    gamma: float = 0.5  # Weight for examiner review rubric value
    hypothesis_weights: Dict[str, float] = field(default_factory=dict)
    group_weights: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.alpha < 0 or self.beta < 0 or self.gamma < 0:
            raise ValueError(
                f"Objective weights must be non-negative. Got alpha={self.alpha}, beta={self.beta}, gamma={self.gamma}"
            )
        for h, w in self.hypothesis_weights.items():
            if w < 0:
                raise ValueError(f"Hypothesis weight for '{h}' must be non-negative, got {w}")
        for g, w in self.group_weights.items():
            if w < 0:
                raise ValueError(f"Group weight for '{g}' must be non-negative, got {w}")

    @property
    def explanation(self) -> str:
        return (
            f"Objective Version {self.version}: "
            f"alpha={self.alpha} (rewards distinct hypothesis coverage with diminishing returns), "
            f"beta={self.beta} (rewards group diversity across assets, categories, and periods), "
            f"gamma={self.gamma} (rewards rubric-based review importance)."
        )


class SubmodularReviewObjective:
    """Evaluates the diminishing-returns submodular objective function F(S)."""

    def __init__(self, weights: Optional[ObjectiveWeights] = None):
        self.weights = weights or ObjectiveWeights()

    def evaluate(self, selected_units: Iterable[CandidateUnit]) -> float:
        """Calculates F(S) for a set of selected candidate units."""
        units_list = list(selected_units)
        if not units_list:
            return 0.0

        # Term 1: Hypothesis Coverage sum_h(w_h * min(1, sum_{i in S} coverage_i_h))
        hyp_coverage_accum: Dict[str, float] = {}
        for u in units_list:
            for h, cov in u.coverage_weights.items():
                hyp_coverage_accum[h] = hyp_coverage_accum.get(h, 0.0) + cov

        term_alpha = 0.0
        for h, total_cov in hyp_coverage_accum.items():
            w_h = self.weights.hypothesis_weights.get(h, 1.0)
            term_alpha += w_h * min(1.0, total_cov)

        # Term 2: Group Diversity sum_g(w_g * min(1, count_g))
        # Groups are defined by key:value pairs (e.g. "asset:SRV-1", "category:POL-INV-001", "period:2026-08")
        group_counts: Dict[str, int] = {}
        for u in units_list:
            for dim, val in u.group_keys.items():
                g_key = f"{dim}:{val}"
                group_counts[g_key] = group_counts.get(g_key, 0) + 1

        term_beta = 0.0
        for g_key, count in group_counts.items():
            w_g = self.weights.group_weights.get(g_key, 1.0)
            term_beta += w_g * min(1.0, float(count))

        # Term 3: Review Value sum_{i in S} review_value_i
        term_gamma = sum(u.review_value for u in units_list)

        return (
            self.weights.alpha * term_alpha
            + self.weights.beta * term_beta
            + self.weights.gamma * term_gamma
        )

    def marginal_gain(
        self, candidate: CandidateUnit, current_selection: List[CandidateUnit]
    ) -> float:
        """Calculates Delta F(candidate | S) = F(S union {candidate}) - F(S)."""
        current_score = self.evaluate(current_selection)
        new_score = self.evaluate(current_selection + [candidate])
        return max(0.0, new_score - current_score)

    def marginal_efficiency(
        self, candidate: CandidateUnit, current_selection: List[CandidateUnit]
    ) -> float:
        """Calculates marginal gain per estimated review minute: Delta F / cost."""
        if candidate.estimated_review_minutes <= 0:
            raise ValueError(
                f"Candidate {candidate.unit_id} cost must be positive, got {candidate.estimated_review_minutes}"
            )
        gain = self.marginal_gain(candidate, current_selection)
        return gain / candidate.estimated_review_minutes

    def get_coverage_breakdown(
        self, selected_units: Iterable[CandidateUnit], all_hypotheses: Set[str]
    ) -> Dict[str, Any]:
        """Provides a detailed breakdown of covered and uncovered hypotheses."""
        units_list = list(selected_units)
        hyp_coverage: Dict[str, float] = {h: 0.0 for h in all_hypotheses}
        for u in units_list:
            for h, cov in u.coverage_weights.items():
                hyp_coverage[h] = hyp_coverage.get(h, 0.0) + cov

        covered = {h: cov for h, cov in hyp_coverage.items() if cov >= 1.0}
        partially_covered = {h: cov for h, cov in hyp_coverage.items() if 0.0 < cov < 1.0}
        uncovered = [h for h, cov in hyp_coverage.items() if cov == 0.0]

        groups_covered: Set[str] = set()
        for u in units_list:
            for dim, val in u.group_keys.items():
                groups_covered.add(f"{dim}:{val}")

        return {
            "covered_hypotheses": covered,
            "partially_covered_hypotheses": partially_covered,
            "uncovered_hypotheses": uncovered,
            "distinct_hypotheses_covered_count": len(covered) + len(partially_covered),
            "total_hypotheses_count": len(all_hypotheses),
            "groups_covered_count": len(groups_covered),
            "total_review_value": sum(u.review_value for u in units_list),
            "total_estimated_minutes": sum(u.estimated_review_minutes for u in units_list),
        }
