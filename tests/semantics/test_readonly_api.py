"""Acceptance tests verifying strictly read-only similarity retrieval and run-frozen provenance."""

from __future__ import annotations

import datetime
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models.assessment import AnalysisRun, Finding
from db.models.evidence import RawRecord, Submission
from db.models.semantic_evidence import FindingSimilarPassage, SemanticPassageChunk
from packages.analytics.service import AnalysisService
from tests.conftest import authenticate_user


def seed_test_submission(db: Session, entity_id: str = "CSE-BANK-01") -> Submission:
    """Helper creating a committed submission with case records."""
    now = datetime.datetime.now(datetime.timezone.utc)
    sub = Submission(
        id=f"sub-test-{entity_id}",
        entity_id=entity_id,
        period_start=now - datetime.timedelta(days=30),
        period_end=now,
        source_timezone="UTC",
        status="committed",
        revision=1,
        manifest_json=json.dumps(
            {
                "manifest_version": "1.0.0",
                "entity_id": entity_id,
                "period_start": (now - datetime.timedelta(days=30)).isoformat(),
                "period_end": now.isoformat(),
                "sources": [
                    {
                        "source_id": "src-cases",
                        "record_type": "cases",
                        "declared_row_count": 2,
                        "export_scope": "Cases",
                        "lineage": "SIEM",
                        "sampling_method": "full_population",
                    }
                ],
            }
        ),
    )
    db.add(sub)
    db.flush()

    # Raw and normalized records
    case_payload_1 = {
        "case_id": "CASE-TEST-01",
        "title": "Automated vulnerability scanner activity",
        "severity": "LOW",
        "status": "CLOSED",
        "created_at": (now - datetime.timedelta(days=5)).isoformat(),
        "closed_at": (now - datetime.timedelta(days=5, minutes=-2)).isoformat(),
        "disposition": "BENIGN_SCANNER_VERIFIED",
    }
    case_payload_2 = {
        "case_id": "CASE-TEST-02",
        "title": "Routine approved vulnerability scan",
        "severity": "LOW",
        "status": "CLOSED",
        "created_at": (now - datetime.timedelta(days=6)).isoformat(),
        "closed_at": (now - datetime.timedelta(days=6, minutes=-1)).isoformat(),
        "disposition": "BENIGN_SCANNER_VERIFIED",
    }

    raw1 = RawRecord(
        submission_id=sub.id,
        source_id="src-cases",
        record_type="cases",
        row_locator="row:1",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        raw_payload=json.dumps(case_payload_1),
    )
    raw2 = RawRecord(
        submission_id=sub.id,
        source_id="src-cases",
        record_type="cases",
        row_locator="row:2",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b856",
        raw_payload=json.dumps(case_payload_2),
    )
    db.add_all([raw1, raw2])
    db.commit()
    return sub


def test_repeated_get_causes_zero_encoder_calls_and_zero_db_writes(
    client: TestClient, db_session: Session, bank_examiner
):
    """GET /similar-passages is strictly read-only: causes no analytical writes or encoder calls."""
    sub = seed_test_submission(db_session, "CSE-BANK-01")
    service = AnalysisService(db_session)
    run = service.run_assessment(sub.id, "CSE-BANK-01", semantic_mode="auto")

    # Find a generated finding
    finding = db_session.execute(
        select(Finding).where(Finding.run_id == run.id).limit(1)
    ).scalar_one()

    headers = authenticate_user(client, bank_examiner, db_session)

    # Initial counts
    fsp_count_before = db_session.scalar(select(func.count(FindingSimilarPassage.id)))
    chunk_count_before = db_session.scalar(select(func.count(SemanticPassageChunk.id)))
    run_count_before = db_session.scalar(select(func.count(AnalysisRun.id)))

    # Intercept any potential encoder calls
    with patch("packages.analytics.semantics.encoder.SemanticEncoder.encode") as mock_encode:
        for _ in range(5):
            res = client.get(
                f"/api/v1/findings/{finding.id}/similar-passages",
                headers=headers,
            )
            assert res.status_code == 200
            data = res.json()
            assert data["finding_id"] == finding.id
            assert "disclaimer" in data

        # Invariant 1: encoder was NEVER called on GET
        assert mock_encode.call_count == 0

    # Invariant 2: database state was NOT mutated
    fsp_count_after = db_session.scalar(select(func.count(FindingSimilarPassage.id)))
    chunk_count_after = db_session.scalar(select(func.count(SemanticPassageChunk.id)))
    run_count_after = db_session.scalar(select(func.count(AnalysisRun.id)))

    assert fsp_count_before == fsp_count_after
    assert chunk_count_before == chunk_count_after
    assert run_count_before == run_count_after


def test_missing_saved_results_returns_not_computed_without_processing(
    client: TestClient, db_session: Session, bank_examiner
):
    """Finding with no precomputed passages returns not_computed without triggering background work."""
    sub = seed_test_submission(db_session, "CSE-BANK-01")
    service = AnalysisService(db_session)
    run = service.run_assessment(sub.id, "CSE-BANK-01", semantic_mode="auto")

    # Create dummy finding without similarity records
    dummy_finding = Finding(
        id="find-dummy-empty-passages",
        run_id=run.id,
        submission_id=sub.id,
        entity_id="CSE-BANK-01",
        proposition="Dummy test proposition",
        scope="submission:test",
        family="POL-INV-001",
        evidence_state="supported",
        applicable_obligation="Test Obligation",
    )
    db_session.add(dummy_finding)
    db_session.commit()

    headers = authenticate_user(client, bank_examiner, db_session)

    res = client.get(
        f"/api/v1/findings/{dummy_finding.id}/similar-passages",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "not_computed"
    assert data["matches"] == []


def test_mode_off_returns_disabled_status(client: TestClient, db_session: Session, bank_examiner):
    """When semantic_mode='off', run returns status='disabled' with empty matches."""
    sub = seed_test_submission(db_session, "CSE-BANK-01")
    service = AnalysisService(db_session)
    run = service.run_assessment(sub.id, "CSE-BANK-01", semantic_mode="off")

    finding = db_session.execute(
        select(Finding).where(Finding.run_id == run.id).limit(1)
    ).scalar_one()

    headers = authenticate_user(client, bank_examiner, db_session)

    res = client.get(
        f"/api/v1/findings/{finding.id}/similar-passages",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "disabled"
    assert data["method_used"] == "disabled"
    assert data["matches"] == []


def test_cross_entity_access_blocked(client: TestClient, db_session: Session, fintech_examiner):
    """Fintech examiner cannot retrieve passage evidence for a Bank finding."""
    sub = seed_test_submission(db_session, "CSE-BANK-01")
    service = AnalysisService(db_session)
    run = service.run_assessment(sub.id, "CSE-BANK-01", semantic_mode="auto")

    finding = db_session.execute(
        select(Finding).where(Finding.run_id == run.id).limit(1)
    ).scalar_one()

    # Authenticate as Fintech examiner (CSE-FINTECH-02 scope)
    headers = authenticate_user(client, fintech_examiner, db_session)

    res = client.get(
        f"/api/v1/findings/{finding.id}/similar-passages",
        headers=headers,
    )
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
