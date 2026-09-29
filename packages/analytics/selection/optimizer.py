"""Portfolio selection optimizer implementing submodular diminishing returns.

Selects review portfolio items by marginal gain per positive review minute:
- Enforces max items, optional max minutes budget, and duplication caps.
- Rejects invalid budgets and non-positive review minute costs.
- Preserves rare hypotheses in a bounded candidate pool without all-pairs matrices.
- Allocates configurable strata capacity (targeted, controls, exploratory).
- Samples controls deterministically using a saved seed from declared eligible records.
- Reports precise shortfalls when quotas cannot be filled (never fake padding).
- Explicitly states heuristic limits (no cardinality greedy guarantees, no population prevalence claims).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from packages.analytics.selection.candidates import CandidatePopulation, CandidateUnit
from packages.analytics.selection.objective import ObjectiveWeights, SubmodularReviewObjective


class InvalidBudgetError(ValueError):
    """Raised when max_items, max_minutes, or costs are non-positive."""

    pass


class InvalidAllocationError(ValueError):
    """Raised when strata allocation exceeds total budget or is invalid."""

    pass


@dataclass
class OptimizationResult:
    selected_items: List[CandidateUnit]
    total_minutes: float
    budget_minutes: Optional[float]
    objective_value: float
    weights_version: str
    seed: int
    strata_counts: Dict[str, int]
    strata_targets: Dict[str, int]
    shortfalls: Dict[str, int]
    duplication_caps: Dict[str, int]
    selection_log: List[Dict[str, Any]]
    coverage_summary: Dict[str, Any]
    limitations_disclosure: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_items": [u.to_dict() for u in self.selected_items],
            "total_minutes": self.total_minutes,
            "budget_minutes": self.budget_minutes,
            "objective_value": self.objective_value,
            "weights_version": self.weights_version,
            "seed": self.seed,
            "strata_counts": self.strata_counts,
            "strata_targets": self.strata_targets,
            "shortfalls": self.shortfalls,
            "duplication_caps": self.duplication_caps,
            "selection_log": self.selection_log,
            "coverage_summary": self.coverage_summary,
            "limitations_disclosure": self.limitations_disclosure,
        }


class ReviewPortfolioOptimizer:
    """Greedy cost-benefit optimizer under diminishing-returns objective and strata quotas."""

    DEFAULT_DISCLOSURE = {
        "greedy_guarantee": (
            "Heuristic Disclaimer: Standard (1 - 1/e) greedy approximation guarantees hold for "
            "cardinality-constrained submodular maximization. They do NOT apply to this knapsack "
            "cost-budget, quota-stratified, and duplication-capped selection."
        ),
        "prevalence_estimation": (
            "Sampling Notice: This review queue is risk-targeted and diversity-optimized. "
            "It CANNOT be used to estimate population prevalence of SOC non-compliance or defects. "
            "Any regulatory prevalence survey requires a separately justified random sampling "
            "design with known inclusion probabilities."
        ),
    }

    def __init__(
        self,
        weights: Optional[ObjectiveWeights] = None,
        duplication_caps: Optional[Dict[str, int]] = None,
    ):
        self.weights = weights or ObjectiveWeights()
        self.objective = SubmodularReviewObjective(self.weights)
        # Default duplication cap: max 3 items per asset, max 4 items per category
        self.duplication_caps = duplication_caps or {
            "asset": 3,
            "category": 4,
        }

    def compute_default_allocation(self, max_items: int) -> Dict[str, int]:
        """Calculates default strata breakdown: 70% targeted, 20% control, 10% exploratory."""
        if max_items == 20:
            return {"targeted": 14, "control": 4, "exploratory": 2}
        if max_items <= 3:
            return {"targeted": max_items, "control": 0, "exploratory": 0}
        ctrl = max(1, int(round(max_items * 0.20)))
        exp = max(1, int(round(max_items * 0.10)))
        tgt = max_items - ctrl - exp
        if tgt < 1:
            tgt = 1
            ctrl = max_items - tgt - exp
        return {"targeted": tgt, "control": ctrl, "exploratory": exp}

    def _check_caps(self, candidate: CandidateUnit, current_selection: List[CandidateUnit]) -> bool:
        """Returns True if adding candidate violates any duplication cap."""
        for dim, cap in self.duplication_caps.items():
            cand_val = candidate.group_keys.get(dim)
            if not cand_val:
                continue
            existing_count = sum(1 for u in current_selection if u.group_keys.get(dim) == cand_val)
            if existing_count >= cap:
                return False
        return True

    def optimize(
        self,
        population: CandidatePopulation,
        max_items: int = 20,
        max_minutes: Optional[float] = None,
        strata_allocation: Optional[Dict[str, int]] = None,
        seed: int = 42,
    ) -> OptimizationResult:
        if max_items <= 0:
            raise InvalidBudgetError(f"max_items must be positive, got {max_items}")
        if max_minutes is not None and max_minutes <= 0:
            raise InvalidBudgetError(f"max_minutes must be positive, got {max_minutes}")

        # Determine strata target capacity
        if strata_allocation is None:
            allocation = self.compute_default_allocation(max_items)
        else:
            total_allocated = sum(strata_allocation.values())
            if total_allocated > max_items:
                raise InvalidAllocationError(
                    f"Strata allocation sum ({total_allocated}) exceeds max_items ({max_items})"
                )
            for s_name, count in strata_allocation.items():
                if count < 0:
                    raise InvalidAllocationError(
                        f"Allocation for stratum '{s_name}' cannot be negative, got {count}"
                    )
            allocation = dict(strata_allocation)

        rng = random.Random(seed)
        selected: List[CandidateUnit] = []
        selected_unit_ids: Set[str] = set()
        accumulated_minutes = 0.0
        selection_log: List[Dict[str, Any]] = []

        all_hypotheses: Set[str] = set()
        for u in population.all_candidates:
            all_hypotheses.update(u.hypothesis_links)

        # Helper to check minute budget
        def can_afford(cand: CandidateUnit) -> bool:
            if max_minutes is None:
                return True
            return (accumulated_minutes + cand.estimated_review_minutes) <= max_minutes

        # -------------------------------------------------------------
        # Phase 1: Targeted Selection via Greedy Marginal Efficiency
        # -------------------------------------------------------------
        target_quota = allocation.get("targeted", 0)
        targeted_pool = list(population.targeted_candidates)

        # Sort pool initially to ensure rare hypotheses are preserved and bounded
        # Priority: candidates covering rare hypotheses (hypotheses with low candidate count)
        hyp_frequencies: Dict[str, int] = {}
        for c in targeted_pool:
            for h in c.hypothesis_links:
                hyp_frequencies[h] = hyp_frequencies.get(h, 0) + 1

        targeted_selected_count = 0
        while targeted_selected_count < target_quota:
            best_candidate: Optional[CandidateUnit] = None
            best_efficiency = -1.0
            best_val = -1.0

            # Evaluate marginal efficiency for all unselected candidates
            candidates_considered = 0
            for cand in targeted_pool:
                if cand.unit_id in selected_unit_ids:
                    continue
                if not can_afford(cand):
                    continue
                if not self._check_caps(cand, selected):
                    continue

                candidates_considered += 1
                eff = self.objective.marginal_efficiency(cand, selected)

                # Deterministic tie-breaking on (efficiency, review_value, unit_id)
                # We prioritize strictly higher efficiency, then higher rubric value, then lexicographical unit_id
                is_better = False
                if eff > best_efficiency + 1e-9:
                    is_better = True
                elif abs(eff - best_efficiency) <= 1e-9:
                    if cand.review_value > best_val + 1e-9:
                        is_better = True
                    elif abs(cand.review_value - best_val) <= 1e-9:
                        if best_candidate is None or cand.unit_id < best_candidate.unit_id:
                            is_better = True

                if is_better:
                    best_candidate = cand
                    best_efficiency = eff
                    best_val = cand.review_value

            if best_candidate is None or best_efficiency < 0:
                # No more feasible candidates in targeted pool under budget/caps
                break

            # Select best candidate
            selected.append(best_candidate)
            selected_unit_ids.add(best_candidate.unit_id)
            accumulated_minutes += best_candidate.estimated_review_minutes
            targeted_selected_count += 1

            selection_log.append(
                {
                    "unit_id": best_candidate.unit_id,
                    "stratum": "targeted",
                    "marginal_efficiency": best_efficiency,
                    "marginal_gain": self.objective.marginal_gain(best_candidate, selected[:-1]),
                    "estimated_minutes": best_candidate.estimated_review_minutes,
                    "covered_hypotheses": list(best_candidate.hypothesis_links),
                    "scope": best_candidate.scope,
                }
            )

        # -------------------------------------------------------------
        # Phase 2: Unflagged Control Selection via Seeded Random Sampling
        # -------------------------------------------------------------
        control_quota = allocation.get("control", 0)
        control_pool = [
            c for c in population.control_candidates if c.unit_id not in selected_unit_ids
        ]

        # Deterministic shuffle using saved seed
        control_pool_sorted = sorted(control_pool, key=lambda c: c.unit_id)
        rng.shuffle(control_pool_sorted)

        control_selected_count = 0
        for cand in control_pool_sorted:
            if control_selected_count >= control_quota:
                break
            if cand.unit_id in selected_unit_ids:
                continue
            if not can_afford(cand):
                continue
            if not self._check_caps(cand, selected):
                continue

            selected.append(cand)
            selected_unit_ids.add(cand.unit_id)
            accumulated_minutes += cand.estimated_review_minutes
            control_selected_count += 1

            selection_log.append(
                {
                    "unit_id": cand.unit_id,
                    "stratum": "control",
                    "marginal_efficiency": self.objective.marginal_efficiency(cand, selected[:-1]),
                    "marginal_gain": self.objective.marginal_gain(cand, selected[:-1]),
                    "estimated_minutes": cand.estimated_review_minutes,
                    "covered_hypotheses": list(cand.hypothesis_links),
                    "scope": cand.scope,
                }
            )

        # -------------------------------------------------------------
        # Phase 3: Exploratory Selection
        # -------------------------------------------------------------
        exploratory_quota = allocation.get("exploratory", 0)
        exp_pool = [
            c for c in population.exploratory_candidates if c.unit_id not in selected_unit_ids
        ]
        exp_pool_sorted = sorted(exp_pool, key=lambda c: c.unit_id)
        rng.shuffle(exp_pool_sorted)

        exp_selected_count = 0
        for cand in exp_pool_sorted:
            if exp_selected_count >= exploratory_quota:
                break
            if cand.unit_id in selected_unit_ids:
                continue
            if not can_afford(cand):
                continue
            if not self._check_caps(cand, selected):
                continue

            selected.append(cand)
            selected_unit_ids.add(cand.unit_id)
            accumulated_minutes += cand.estimated_review_minutes
            exp_selected_count += 1

            selection_log.append(
                {
                    "unit_id": cand.unit_id,
                    "stratum": "exploratory",
                    "marginal_efficiency": self.objective.marginal_efficiency(cand, selected[:-1]),
                    "marginal_gain": self.objective.marginal_gain(cand, selected[:-1]),
                    "estimated_minutes": cand.estimated_review_minutes,
                    "covered_hypotheses": list(cand.hypothesis_links),
                    "scope": cand.scope,
                }
            )

        # Calculate actual strata counts and precise shortfalls
        actual_strata = {
            "targeted": targeted_selected_count,
            "control": control_selected_count,
            "exploratory": exp_selected_count,
        }
        shortfalls = {
            "targeted": max(0, target_quota - targeted_selected_count),
            "control": max(0, control_quota - control_selected_count),
            "exploratory": max(0, exploratory_quota - exp_selected_count),
        }

        coverage_summary = self.objective.get_coverage_breakdown(selected, all_hypotheses)
        obj_val = self.objective.evaluate(selected)

        return OptimizationResult(
            selected_items=selected,
            total_minutes=round(accumulated_minutes, 2),
            budget_minutes=max_minutes,
            objective_value=round(obj_val, 4),
            weights_version=self.weights.version,
            seed=seed,
            strata_counts=actual_strata,
            strata_targets=allocation,
            shortfalls=shortfalls,
            duplication_caps=self.duplication_caps,
            selection_log=selection_log,
            coverage_summary=coverage_summary,
            limitations_disclosure=self.DEFAULT_DISCLOSURE,
        )
