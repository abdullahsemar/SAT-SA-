"""Tests for supervisory decisions, audit history, optimistic concurrency, and evidence requests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db.models.access import User
from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import Submission
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


def test_decision_lifecycle_and_finding_immutability(
    client: TestClient, db_session: Session, bank_examiner: User, review_scenario
):
    """Verifies decision recording, superseding, version history, and machine finding immutability."""
    headers = authenticate_user(client, bank_examiner, db_session)

    # 1. Setup submission and analysis run
    sub = Submission(
        id="SUB-DEC-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment("SUB-DEC-01", "CSE-BANK-01", semantic_mode="off")
    findings = analysis_service.list_findings(run_id=run.id)
    target_finding = findings[0]
    initial_prop = target_finding.rationale
    initial_state = target_finding.evidence_state

    # 2. Record first finding decision: substantiated
    res1 = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={
            "state": "substantiated",
            "rationale": "Examined escalation logs; confirmed that alert response exceeded cutoff by 4 hours.",
            "cited_evidence_ids": [],
        },
        headers=headers,
    )
    assert res1.status_code == 201
    d1 = res1.json()
    assert d1["state"] == "substantiated"
    assert d1["version"] == 1
    assert d1["superseded_decision_id"] is None

    # Invariant: Machine finding remains 100% untainted
    refreshed_finding = db_session.get(Finding, target_finding.finding_id)
    assert refreshed_finding.proposition == initial_prop
    assert refreshed_finding.evidence_state == initial_state

    # 3. Supersede earlier decision: correction to additional_evidence_required
    res2 = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={
            "state": "additional_evidence_required",
            "rationale": "SOC manager submitted secondary ticket showing external maintenance outage. Need change ticket.",
            "cited_evidence_ids": [],
            "superseded_decision_id": d1["id"],
        },
        headers=headers,
    )
    assert res2.status_code == 201
    d2 = res2.json()
    assert d2["state"] == "additional_evidence_required"
    assert d2["version"] == 2
    assert d2["superseded_decision_id"] == d1["id"]

    # 4. Fetch decision history: preserves both decisions immutably
    res3 = client.get(f"/api/v1/findings/{target_finding.finding_id}/decisions", headers=headers)
    assert res3.status_code == 200
    history = res3.json()
    assert len(history) == 2
    assert history[0]["id"] == d1["id"]
    assert history[1]["id"] == d2["id"]


def test_optimistic_concurrency_conflict(
    client: TestClient, db_session: Session, bank_examiner: User, review_scenario
):
    """Verifies that attempting to supersede an already superseded decision returns 409 CONFLICT."""
    headers = authenticate_user(client, bank_examiner, db_session)

    sub = Submission(
        id="SUB-DEC-02",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment("SUB-DEC-02", "CSE-BANK-01", semantic_mode="off")
    target_finding = analysis_service.list_findings(run_id=run.id)[0]

    # Initial decision
    r1 = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={"state": "substantiated", "rationale": "Initial review.", "cited_evidence_ids": []},
        headers=headers,
    )
    d1_id = r1.json()["id"]

    # First update succeeds
    r2 = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={
            "state": "not_substantiated",
            "rationale": "Updated determination.",
            "cited_evidence_ids": [],
            "superseded_decision_id": d1_id,
        },
        headers=headers,
    )
    assert r2.status_code == 201

    # Concurrent stale update attempting to supersede d1_id again must raise 409 CONFLICT
    r3 = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={
            "state": "not_applicable",
            "rationale": "Conflicting stale update.",
            "cited_evidence_ids": [],
            "superseded_decision_id": d1_id,
        },
        headers=headers,
    )
    assert r3.status_code == 409
    assert "already been superseded" in r3.json()["message"]


def test_scope_checked_evidence_validation_rejects_foreign_ids(
    client: TestClient, db_session: Session, bank_examiner: User, review_scenario
):
    """Verifies that citing out-of-scope or foreign evidence IDs is rejected with 400."""
    headers = authenticate_user(client, bank_examiner, db_session)

    sub = Submission(
        id="SUB-DEC-03",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment("SUB-DEC-03", "CSE-BANK-01", semantic_mode="off")
    target_finding = analysis_service.list_findings(run_id=run.id)[0]

    # Post with fraudulent / foreign evidence ID
    res = client.post(
        f"/api/v1/findings/{target_finding.finding_id}/decisions",
        json={
            "state": "substantiated",
            "rationale": "Citing fake evidence ID.",
            "cited_evidence_ids": ["FAKE-EV-FOREIGN-999"],
        },
        headers=headers,
    )
    assert res.status_code == 400
    assert "Out-of-scope or unverified cited evidence ID" in res.json()["message"]


def test_review_and_save_unflagged_control_without_fake_finding(
    client: TestClient, db_session: Session, bank_examiner: User, review_scenario
):
    """Verifies reviewing and saving an unflagged control item succeeds without creating a fake machine finding."""
    headers = authenticate_user(client, bank_examiner, db_session)

    sub = Submission(
        id="SUB-DEC-04",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, review_scenario)
    db_session.add(sub)
    db_session.commit()

    analysis_service = AnalysisService(db_session)
    run = analysis_service.run_assessment("SUB-DEC-04", "CSE-BANK-01", semantic_mode="off")
    initial_findings_count = len(analysis_service.list_findings(run_id=run.id))

    # Create review portfolio
    p_res = client.post(
        "/api/v1/review-portfolios",
        json={"run_id": run.id, "max_items": 10, "seed": 42},
        headers=headers,
    )
    assert p_res.status_code == 201
    portfolio = p_res.json()

    # Find control item
    control_items = [it for it in portfolio["items"] if it["stratum"] == "control"]
    assert len(control_items) > 0
    ctrl_item = control_items[0]
    assert ctrl_item["finding_id"] is None

    # Record item-level review decision
    dec_res = client.post(
        f"/api/v1/review-items/{ctrl_item['id']}/decisions",
        json={
            "state": "reviewed_no_concern",
            "rationale": "Sampled unflagged control case. Verified triage steps followed standard playbook.",
            "cited_evidence_ids": [],
        },
        headers=headers,
    )
    assert dec_res.status_code == 201
    item_dec = dec_res.json()
    assert item_dec["state"] == "reviewed_no_concern"
    assert item_dec["review_item_id"] == ctrl_item["id"]
    assert item_dec["finding_id"] is None

    # Verify no fake finding was injected into the machine findings table
    current_findings_count = len(analysis_service.list_findings(run_id=run.id))
    assert current_findings_count == initial_findings_count, (
        "Control reviews must NEVER create machine findings"
    )


def test_evidence_requests_local_and_distinguishing_question(
    client: TestClient, db_session: Session, bank_examiner: User
):
    """Verifies that evidence requests require distinguishing question and save as local records."""
    headers = authenticate_user(client, bank_examiner, db_session)

    # Missing question or too short -> 422
    res_bad = client.post(
        "/api/v1/evidence-requests",
        json={
            "finding_id": "dummy-find-id",
            "missing_artifact": "Log file",
            "distinguishing_question": "send data",  # too short (< 10 chars)
            "responsible_owner": "SOC Analyst",
            "due_date": "2026-10-01T00:00:00Z",
        },
        headers=headers,
    )
    assert res_bad.status_code == 422

    # Create valid submission and run in db first
    sub = Submission(
        id="SUB-REQ-01",
        entity_id="CSE-BANK-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    db_session.add(sub)
    db_session.commit()

    run = AnalysisRun(
        id="RUN-REQ-01",
        submission_id="SUB-REQ-01",
        entity_id="CSE-BANK-01",
        status="completed",
        input_hash="hash123",
        cutoff_time=sub.period_end,
    )
    db_session.add(run)
    db_session.commit()

    # Create dummy finding in db
    finding = Finding(
        id="FIND-REQ-01",
        run_id="RUN-REQ-01",
        submission_id="SUB-REQ-01",
        entity_id="CSE-BANK-01",
        proposition="Overdue escalation",
        scope="case:CASE-100",
        family="POL-ESC-002",
        evidence_state="potential_concern",
        applicable_obligation="Escalation Timeliness",
    )
    db_session.add(finding)
    db_session.commit()

    # Valid evidence request
    res_good = client.post(
        "/api/v1/evidence-requests",
        json={
            "finding_id": "FIND-REQ-01",
            "missing_artifact": "Sysmon process spawn tree export for host 10.100.1.10",
            "distinguishing_question": (
                "Provide parent-child process relationship to distinguish authorized system cron "
                "from unauthorized remote command injection."
            ),
            "responsible_owner": "Tier 2 SOC Incident Lead",
            "due_date": "2026-10-05T18:00:00Z",
        },
        headers=headers,
    )
    assert res_good.status_code == 201
    ev_req = res_good.json()
    assert ev_req["entity_id"] == "CSE-BANK-01"
    assert ev_req["status"] == "open"
    assert "distinguish authorized system cron" in ev_req["distinguishing_question"]
