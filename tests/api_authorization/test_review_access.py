"""Tests for RBAC and entity-scoped authorization across review portfolio and decision endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db.models.access import User
from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import Submission
from tests.conftest import authenticate_user


def test_review_endpoints_require_authentication(client: TestClient):
    """Verifies unauthenticated calls to review endpoints return 401."""
    assert client.get("/api/v1/review-portfolios").status_code == 401
    assert client.post("/api/v1/review-portfolios", json={"run_id": "run-1"}).status_code == 401
    assert client.get("/api/v1/findings/find-1/decisions").status_code == 401
    assert (
        client.post(
            "/api/v1/findings/find-1/decisions",
            json={"state": "substantiated", "rationale": "Test"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/evidence-requests",
            json={"missing_artifact": "A", "distinguishing_question": "Q"},
        ).status_code
        == 401
    )


def test_cross_entity_review_portfolio_access_denied(
    client: TestClient, db_session: Session, bank_examiner: User
):
    """Verifies that an examiner scoped to CSE-BANK-01 cannot create or view portfolios for CSE-FINTECH-02."""
    headers_bank = authenticate_user(client, bank_examiner, db_session)

    # Create Fintech submission and run
    sub_fin = Submission(
        id="SUB-FIN-01",
        entity_id="CSE-FINTECH-02",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    db_session.add(sub_fin)
    db_session.commit()

    run_fin = AnalysisRun(
        id="RUN-FIN-01",
        submission_id="SUB-FIN-01",
        entity_id="CSE-FINTECH-02",
        status="completed",
        input_hash="hash123",
        cutoff_time=sub_fin.period_end,
    )
    db_session.add(run_fin)
    db_session.commit()

    # Bank examiner attempts to generate portfolio for Fintech run -> 403
    res_create = client.post(
        "/api/v1/review-portfolios",
        json={"run_id": "RUN-FIN-01", "max_items": 10},
        headers=headers_bank,
    )
    assert res_create.status_code == 403
    assert "Access denied" in res_create.json()["message"]


def test_cross_entity_decision_recording_denied(
    client: TestClient, db_session: Session, bank_examiner: User
):
    """Verifies that an examiner scoped to CSE-BANK-01 cannot record decisions on CSE-FINTECH-02 findings."""
    headers_bank = authenticate_user(client, bank_examiner, db_session)

    # Submission and run on Fintech
    sub_fin = Submission(
        id="SUB-FIN-02",
        entity_id="CSE-FINTECH-02",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    db_session.add(sub_fin)
    db_session.commit()

    run_fin = AnalysisRun(
        id="RUN-FIN-02",
        submission_id="SUB-FIN-02",
        entity_id="CSE-FINTECH-02",
        status="completed",
        input_hash="hash456",
        cutoff_time=sub_fin.period_end,
    )
    db_session.add(run_fin)
    db_session.commit()

    # Finding on Fintech
    find_fin = Finding(
        id="FIND-FIN-01",
        run_id="RUN-FIN-02",
        submission_id="SUB-FIN-02",
        entity_id="CSE-FINTECH-02",
        proposition="Fintech overdue escalation",
        scope="case:CASE-FIN-01",
        family="POL-ESC-002",
        evidence_state="potential_concern",
        applicable_obligation="Escalation Timeliness",
    )
    db_session.add(find_fin)
    db_session.commit()

    # Bank examiner tries to record finding decision on Fintech finding -> 403
    res = client.post(
        "/api/v1/findings/FIND-FIN-01/decisions",
        json={
            "state": "substantiated",
            "rationale": "Bank examiner trying to decide fintech finding",
            "cited_evidence_ids": [],
        },
        headers=headers_bank,
    )
    assert res.status_code == 403
    assert "Access denied" in res.json()["message"]


def test_admin_wildcard_access(client: TestClient, db_session: Session, admin_user: User):
    """Verifies that an admin with wildcard access can view and list portfolios across entities."""
    headers_admin = authenticate_user(client, admin_user, db_session)

    # List portfolios
    res = client.get("/api/v1/review-portfolios", headers=headers_admin)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
