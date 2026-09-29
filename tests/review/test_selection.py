"""Tests for examiner review portfolio selection, diminishing-returns objective, and optimizer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db.models.evidence import Submission
from packages.analytics.context import AssessmentContext
from packages.analytics.selection.candidates import (
    CandidateGenerator,
    CandidatePopulation,
    CandidateUnit,
)
from packages.analytics.selection.explanations import ExplanationGenerator
from packages.analytics.selection.objective import (
    ObjectiveWeights,
    SubmodularReviewObjective,
)
from packages.analytics.selection.optimizer import (
    InvalidAllocationError,
    InvalidBudgetError,
    ReviewPortfolioOptimizer,
)
from packages.analytics.service import AnalysisService
from tests.scenario_adapter import attach_scenario


@pytest.fixture
def review_scenario():
    scenario_path = (
        Path(__file__).resolve().parent.parent.parent / "synthetic" / "scenarios" / "review.json"
    )
    with open(scenario_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_hand_checkable_diminishing_returns_selection():
    """Hand-checkable fixture verifying diminishing returns over duplicates.

    Scenario:
    - 3 duplicate items covering hypothesis H1 (each has value=3.0, cost=10.0, coverage_H1=1.0)
    - 1 diverse item covering hypothesis H2 (value=2.0, cost=10.0, coverage_H2=1.0)
    - Weights: alpha=2.0, beta=1.0, gamma=0.5. No groups.

    Item A1: H1, cost=10. F({A1}) = 2.0 * min(1, 1.0) + 0.5 * 3.0 = 2.0 + 1.5 = 3.5. Gain/min = 0.35.
    Item A2: H1, cost=10. F({A1, A2}) = 2.0 * min(1, 2.0) + 0.5 * 6.0 = 2.0 + 3.0 = 5.0. Delta = 1.5. Gain/min = 0.15.
    Item B1: H2, cost=10. F({A1, B1}) = 2.0 * (min(1, 1) + min(1, 1)) + 0.5 * (3 + 2) = 4.0 + 2.5 = 6.5.
                          Delta F(B1 | {A1}) = 6.5 - 3.5 = 3.0. Gain/min = 0.30.

    Because Delta(B1 | {A1})/cost = 0.30 > Delta(A2 | {A1})/cost = 0.15,
    greedy selection picks A1 first, then B1 second, resisting duplicate A2!
    """
    weights = ObjectiveWeights(alpha=2.0, beta=0.0, gamma=0.5)
    obj = SubmodularReviewObjective(weights)

    a1 = CandidateUnit(
        unit_id="unit-a1",
        unit_type="case",
        scope="case:CASE-DUP-1",
        finding_id="f-1",
        hypothesis_links=["H1"],
        group_keys={},
        evidence_references=[],
        unknowns=[],
        estimated_review_minutes=10.0,
        what_examiner_could_learn="Check H1",
        review_value=3.0,
        coverage_weights={"H1": 1.0},
    )
    a2 = CandidateUnit(
        unit_id="unit-a2",
        unit_type="case",
        scope="case:CASE-DUP-2",
        finding_id="f-2",
        hypothesis_links=["H1"],
        group_keys={},
        evidence_references=[],
        unknowns=[],
        estimated_review_minutes=10.0,
        what_examiner_could_learn="Check H1 duplicate",
        review_value=3.0,
        coverage_weights={"H1": 1.0},
    )
    b1 = CandidateUnit(
        unit_id="unit-b1",
        unit_type="case",
        scope="case:CASE-DIV-1",
        finding_id="f-3",
        hypothesis_links=["H2"],
        group_keys={},
        evidence_references=[],
        unknowns=[],
        estimated_review_minutes=10.0,
        what_examiner_could_learn="Check H2 diverse",
        review_value=2.0,
        coverage_weights={"H2": 1.0},
    )

    # Initial selection
    gain_a1 = obj.marginal_gain(a1, [])
    gain_b1 = obj.marginal_gain(b1, [])
    assert gain_a1 == 3.5
    assert gain_b1 == 3.0
    # Step 1: A1 is selected
    selected = [a1]

    # Step 2: Compare marginal gain of A2 vs B1
    delta_a2 = obj.marginal_gain(a2, selected)
    delta_b1 = obj.marginal_gain(b1, selected)
    assert delta_a2 == 1.5
    assert delta_b1 == 3.0
    assert delta_b1 > delta_a2, "Diverse hypothesis H2 must beat duplicate H1 on second step"


def test_portfolio_selection_covers_distinct_hypotheses(db_session: Session, review_scenario):
    """Verifies that with many duplicated cases, portfolio covers distinct hypotheses."""
    sub = Submission(
        id="SUB-REV-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    # Run analysis to generate findings
    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment(
        submission_id="SUB-REV-01",
        cse_id="CSE-BANK-01",
        semantic_mode="off",  # Missing ML does not block selection
    )

    ctx = AssessmentContext(sub)
    findings = analysis_service.list_findings(run_id=run.id)

    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(run_id=run.id, findings=findings)

    optimizer = ReviewPortfolioOptimizer()
    res = optimizer.optimize(
        population=population,
        max_items=8,
        strata_allocation={"targeted": 5, "control": 2, "exploratory": 1},
        seed=42,
    )

    # Assert distinct hypotheses are covered
    selected_hypotheses = set()
    for item in res.selected_items:
        selected_hypotheses.update(item.hypothesis_links)

    assert len(selected_hypotheses) >= 3, "Portfolio must cover multiple distinct hypotheses"
    assert res.coverage_summary["distinct_hypotheses_covered_count"] >= 3


def test_missing_coverage_asset_selected_without_case_id(db_session: Session, review_scenario):
    """Verifies at least one asset-period item is selected for missing coverage without a case ID."""
    sub = Submission(
        id="SUB-REV-02",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    ctx = AssessmentContext(sub)
    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(run_id="dummy-run", findings=[])

    # Check that candidate population contains an asset_period unit for the unhealthy sensor
    asset_period_units = [
        u
        for u in population.targeted_candidates
        if u.unit_type == "asset_period" and "SRV-UNHEALTHY-SENSOR-01" in u.scope
    ]
    assert len(asset_period_units) >= 1, (
        "Unhealthy sensor without alerts/cases must generate asset_period candidate"
    )
    sensor_unit = asset_period_units[0]
    assert sensor_unit.finding_id is None, "Missing coverage concern has finding_id=None"

    # Optimize and verify it gets selected
    optimizer = ReviewPortfolioOptimizer()
    res = optimizer.optimize(
        population=population,
        max_items=5,
        strata_allocation={"targeted": 3, "control": 1, "exploratory": 1},
        seed=42,
    )
    selected_scopes = [u.scope for u in res.selected_items]
    assert any("SRV-UNHEALTHY-SENSOR-01" in s for s in selected_scopes)


def test_budgets_caps_and_shortfalls():
    """Verifies item budget, minute budget, duplication caps, and shortfall reporting."""
    weights = ObjectiveWeights()
    optimizer = ReviewPortfolioOptimizer(
        weights=weights,
        duplication_caps={"asset": 1},  # Strict duplication cap: max 1 per asset
    )

    # 3 candidates from the same asset
    c1 = CandidateUnit(
        unit_id="u1",
        unit_type="case",
        scope="case:1",
        finding_id="f1",
        hypothesis_links=["H1"],
        group_keys={"asset": "SRV-DUP"},
        evidence_references=[],
        unknowns=[],
        estimated_review_minutes=10.0,
        what_examiner_could_learn="L1",
        review_value=2.0,
        coverage_weights={"H1": 1.0},
    )
    c2 = CandidateUnit(
        unit_id="u2",
        unit_type="case",
        scope="case:2",
        finding_id="f2",
        hypothesis_links=["H2"],
        group_keys={"asset": "SRV-DUP"},
        evidence_references=[],
        unknowns=[],
        estimated_review_minutes=10.0,
        what_examiner_could_learn="L2",
        review_value=2.0,
        coverage_weights={"H2": 1.0},
    )
    pop = CandidatePopulation(
        run_id="run-1",
        entity_id="CSE-1",
        period_key="2026-08",
        targeted_candidates=[c1, c2],
        control_candidates=[],  # 0 controls available
        exploratory_candidates=[],
        all_candidates=[c1, c2],
        excluded_records=[],
        sampling_frame_summary={},
    )

    # Request 2 controls, but 0 exist -> must report shortfall
    res = optimizer.optimize(
        population=pop,
        max_items=5,
        max_minutes=15.0,  # Only enough for 1 item of 10.0 minutes
        strata_allocation={"targeted": 2, "control": 2, "exploratory": 0},
        seed=42,
    )

    assert res.total_minutes <= 15.0, "Total minutes must not exceed minute budget"
    assert len(res.selected_items) == 1, "Only 1 item can fit within 15 minute budget"
    assert res.shortfalls["control"] == 2, "Must report precise control shortfall of 2"
    assert res.shortfalls["targeted"] == 1, "Must report targeted shortfall of 1"

    # Reject invalid budget/allocations
    with pytest.raises(InvalidBudgetError):
        optimizer.optimize(population=pop, max_items=-1)
    with pytest.raises(InvalidBudgetError):
        optimizer.optimize(population=pop, max_items=5, max_minutes=0)
    with pytest.raises(InvalidAllocationError):
        optimizer.optimize(
            population=pop,
            max_items=2,
            strata_allocation={"targeted": 2, "control": 1, "exploratory": 0},
        )


def test_determinism_and_reopening_preserves_order(db_session: Session, review_scenario):
    """Verifies that the same run/config/seed produces identical portfolios."""
    sub = Submission(
        id="SUB-REV-03",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    ctx = AssessmentContext(sub)
    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(run_id="run-det", findings=[])

    optimizer = ReviewPortfolioOptimizer()
    res1 = optimizer.optimize(population=population, max_items=6, seed=12345)
    res2 = optimizer.optimize(population=population, max_items=6, seed=12345)

    assert [u.unit_id for u in res1.selected_items] == [u.unit_id for u in res2.selected_items]
    assert res1.objective_value == res2.objective_value
    assert res1.total_minutes == res2.total_minutes


def test_control_sampling_frame_and_explanations(review_scenario):
    """Verifies controls are sampled from declared unflagged records and explanations are generated."""
    sub = Submission(
        id="SUB-REV-04",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    ctx = AssessmentContext(sub)
    cand_gen = CandidateGenerator(ctx)
    pop = cand_gen.generate_candidates(run_id="run-ctrl", findings=[])

    assert pop.sampling_frame_summary["eligible_control_cases_count"] > 0
    assert pop.sampling_frame_summary["total_control_eligible_count"] > 0

    optimizer = ReviewPortfolioOptimizer()
    res = optimizer.optimize(
        population=pop,
        max_items=6,
        strata_allocation={"targeted": 2, "control": 3, "exploratory": 1},
        seed=99,
    )

    controls = [it for it in res.selected_items if it.stratum == "control"]
    assert len(controls) == 3
    for ctrl in controls:
        assert ctrl.is_control is True
        assert ctrl.finding_id is None
        # Check explanation
        expl = ExplanationGenerator.generate_item_explanation(ctrl, rank=1)
        assert "unflagged control" in expl["why_selected"]
        assert "what_examiner_could_learn" in expl
        assert "citations" in expl
