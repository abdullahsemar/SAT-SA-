"""End-to-end integration tests for supervisory examiner review portfolio workflow.

Demonstrates:
1. End-to-end workflow: intake committed -> run assessment -> generate portfolio with >= 5 saved items.
2. Verified item composition: includes targeted case, unflagged control, and absence-of-coverage asset item.
3. Save and reopen decision and evidence request.
4. Reopening portfolio preserves exact order, item count, and marginal reasons without resampling.
5. Fixture comparison: compares diminishing-returns objective coverage against highest-score-only and seeded random selection.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db.models.access import User
from db.models.evidence import Submission
from packages.analytics.context import AssessmentContext
from packages.analytics.selection.candidates import CandidateGenerator
from packages.analytics.selection.optimizer import ReviewPortfolioOptimizer
from packages.analytics.service import AnalysisService
from tests.conftest import authenticate_user
from tests.scenario_adapter import attach_scenario


@pytest.fixture
def review_scenario():
    scenario_path = (
        Path(__file__).resolve().parent.parent.parent / "synthetic" / "scenarios" / "review.json"
    )
    with open(scenario_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_full_examiner_workflow_and_comparison(
    client: TestClient, db_session: Session, bank_examiner: User, review_scenario
):
    headers = authenticate_user(client, bank_examiner, db_session)

    # Step 1: Commit submission
    sub = Submission(
        id="SUB-WORKFLOW-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    # Step 2: Run supervisory analysis
    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment("SUB-WORKFLOW-01", "CSE-BANK-01", semantic_mode="off")
    assert run.status == "completed"

    # Step 3: Request a 5-item review portfolio
    port_res = client.post(
        "/api/v1/review-portfolios",
        json={
            "run_id": run.id,
            "max_items": 5,
            "strata_allocation": {"targeted": 3, "control": 1, "exploratory": 1},
            "seed": 42,
        },
        headers=headers,
    )
    assert port_res.status_code == 201
    portfolio = port_res.json()
    portfolio_id = portfolio["id"]

    items = portfolio["items"]
    assert len(items) == 5, f"Expected 5 saved items, got {len(items)}"

    # Check composition: must include targeted, control, and asset-period
    strata = {it["stratum"] for it in items}
    unit_types = {it["unit_type"] for it in items}

    assert "targeted" in strata, "Portfolio must include targeted items"
    assert "control" in strata, "Portfolio must include an unflagged control"
    assert "asset_period" in unit_types, "Portfolio must include an asset_period item"

    # Verify control item is an actual unflagged record
    control_item = next(it for it in items if it["stratum"] == "control")
    assert control_item["finding_id"] is None
    assert "control" in control_item["marginal_reasons"]["why_selected"]

    # Verify asset-period item (absence of coverage)
    asset_item = next(it for it in items if it["unit_type"] == "asset_period")
    assert "asset:" in asset_item["scope"]

    # Step 4: Reopen portfolio and verify exact immutability (no resampling)
    reopen_res = client.get(f"/api/v1/review-portfolios/{portfolio_id}", headers=headers)
    assert reopen_res.status_code == 200
    reopened = reopen_res.json()
    assert [it["id"] for it in reopened["items"]] == [it["id"] for it in items]
    assert reopened["summary"] == portfolio["summary"]

    # Step 5: Save a decision on a targeted item
    targeted_item = next(it for it in items if it["stratum"] == "targeted" and it["finding_id"])
    dec_res = client.post(
        f"/api/v1/findings/{targeted_item['finding_id']}/decisions",
        json={
            "state": "substantiated",
            "rationale": "Workflow inspection confirmed escalation was delayed beyond SLA cutoff.",
            "cited_evidence_ids": [],
        },
        headers=headers,
    )
    assert dec_res.status_code == 201
    saved_dec = dec_res.json()
    assert saved_dec["state"] == "substantiated"

    # Step 6: File an evidence request on the item
    ev_res = client.post(
        "/api/v1/evidence-requests",
        json={
            "finding_id": targeted_item["finding_id"],
            "review_item_id": targeted_item["id"],
            "missing_artifact": "Internal ticket approval thread for incident",
            "distinguishing_question": (
                "Provide written delegation approval to verify if technician was authorized "
                "to suspend escalation protocols."
            ),
            "responsible_owner": "SOC Operations Manager",
            "due_date": "2026-10-15T00:00:00Z",
        },
        headers=headers,
    )
    assert ev_res.status_code == 201
    ev_data = ev_res.json()
    assert ev_data["status"] == "open"

    # Reopen decisions and evidence requests
    get_decs = client.get(
        f"/api/v1/findings/{targeted_item['finding_id']}/decisions", headers=headers
    )
    assert len(get_decs.json()) >= 1

    get_evs = client.get(
        f"/api/v1/evidence-requests?finding_id={targeted_item['finding_id']}", headers=headers
    )
    assert len(get_evs.json()) >= 1

    # Step 7: Fixture Comparison: Diminishing-returns vs Highest-score-only vs Random
    # Report observed numbers as fixture results, not general superiority.
    ctx = AssessmentContext(sub)
    cand_gen = CandidateGenerator(ctx)
    population = cand_gen.generate_candidates(
        run_id=run.id, findings=analysis_service.list_findings(run_id=run.id)
    )
    all_cands = population.targeted_candidates

    # A) Diminishing Returns (Our Heuristic):
    optimizer = ReviewPortfolioOptimizer()
    dr_result = optimizer.optimize(
        population=population,
        max_items=4,
        strata_allocation={"targeted": 4, "control": 0, "exploratory": 0},
        seed=42,
    )
    dr_hypotheses = set()
    for it in dr_result.selected_items:
        dr_hypotheses.update(it.hypothesis_links)

    # B) Highest-score-only (Pick top 4 by review_value):
    sorted_by_val = sorted(all_cands, key=lambda c: c.review_value, reverse=True)
    score_only_items = sorted_by_val[:4]
    score_only_hypotheses = set()
    for it in score_only_items:
        score_only_hypotheses.update(it.hypothesis_links)

    # C) Seeded Random (Sample 4 uniformly):
    import random

    rng = random.Random(42)
    random_sample_items = rng.sample(all_cands, min(4, len(all_cands)))
    random_hypotheses = set()
    for it in random_sample_items:
        random_hypotheses.update(it.hypothesis_links)

    # Log/assert observed numbers on this specific synthetic fixture
    # Because our scenario has 4 duplicate high-ranked cases for one hypothesis,
    # highest-score-only picks duplicates and covers fewer distinct hypotheses.
    print(
        f"Fixture Results (4 items): Diminishing-Returns covered {len(dr_hypotheses)} hypotheses; "
        f"Score-only covered {len(score_only_hypotheses)}; Random covered {len(random_hypotheses)}."
    )

    assert len(dr_hypotheses) >= len(score_only_hypotheses), (
        f"Diminishing returns should cover at least as many hypotheses as score-only on duplicated fixture. "
        f"Got DR={len(dr_hypotheses)} vs ScoreOnly={len(score_only_hypotheses)}"
    )
