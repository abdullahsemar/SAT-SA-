"""Negative test suite for citation and provenance validation in the evaluation harness.

Verifies that citation validation strictly rejects:
1. Corrupted cited sha256 hashes or constant placeholder hashes.
2. Replaced or fabricated/placeholder record IDs.
3. Cross-entity or cross-submission citations.
4. Missing required citations on factual supported/adverse findings.
5. Uploaded source file bytes tampered on disk.
6. Proves broken citations cause scenario evaluation to FAIL.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.models import Base
from db.models.evidence import NormalizedRecord
from evaluation.citations import validate_citations
from evaluation.ingest_scenario import ingest_scenario
from packages.analytics.service import AnalysisService


@pytest.fixture
def eval_scenario():
    scenario_path = (
        Path(__file__).resolve().parent.parent.parent
        / "synthetic"
        / "scenarios"
        / "final-validation.json"
    )
    with open(scenario_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    worlds = data.get("worlds", [])
    for w in worlds:
        if w.get("scenario_id") == "WORLD-02-KPI-PROCEDURAL-CLOSURE":
            return deepcopy(w)
    return deepcopy(worlds[0])


@pytest.fixture
def eval_env(eval_scenario, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)

    sub, quality = ingest_scenario(eval_scenario, session, tmp_path)
    analysis_service = AnalysisService(session)
    run = analysis_service.run_assessment(
        submission_id=sub.id,
        cse_id=eval_scenario.get("cse_id", "CSE-BANK-01"),
        semantic_mode="off",
    )
    findings = analysis_service.list_findings(run_id=run.id)

    # Initial validation must pass cleanly with 0 broken citations
    initial_broken = validate_citations(findings, session, sub)
    assert len(initial_broken) == 0, f"Expected 0 initial broken citations, got {initial_broken}"

    yield session, sub, findings, tmp_path

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_citation_negative_corrupted_hash(eval_env):
    """Corrupting a cited hash must be rejected with citation_provenance_mismatch."""
    session, sub, findings, _ = eval_env
    f = next(f for f in findings if f.supporting_records)
    refs = f.supporting_records
    refs[0]["sha256"] = "deadbeef" * 8
    f.supporting_sources_json = json.dumps(refs)
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "citation_provenance_mismatch" in reasons


def test_citation_negative_constant_placeholder_hash(eval_env):
    """Constant placeholder hash like '0' * 64 must be rejected."""
    session, sub, findings, _ = eval_env
    f = next(f for f in findings if f.supporting_records)
    refs = f.supporting_records
    refs[0]["sha256"] = "0" * 64
    f.supporting_sources_json = json.dumps(refs)
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "constant_placeholder_or_invalid_hash" in reasons


def test_citation_negative_replaced_record_id(eval_env):
    """Replacing a cited record ID with an unresolvable ID must be rejected."""
    session, sub, findings, _ = eval_env
    f = next(f for f in findings if f.supporting_records)
    refs = f.supporting_records
    refs[0]["record_id"] = "non-existent-uuid-9999"
    f.supporting_sources_json = json.dumps(refs)
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "unresolvable_or_cross_scope_record" in reasons


def test_citation_negative_fabricated_placeholder_record_id(eval_env):
    """Placeholder string like 'dummy' or 'placeholder' must be rejected."""
    session, sub, findings, _ = eval_env
    f = next(f for f in findings if f.supporting_records)
    refs = f.supporting_records
    refs[0]["record_id"] = "dummy"
    f.supporting_sources_json = json.dumps(refs)
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "fabricated_or_placeholder_record_id" in reasons


def test_citation_negative_cross_scope_entity_or_submission(eval_env):
    """Citations pointing to another entity or submission scope must be rejected."""
    session, sub, findings, _ = eval_env
    f = next(f for f in findings if f.supporting_records)
    rec_id = f.supporting_records[0]["record_id"]
    rec = session.get(NormalizedRecord, rec_id)
    assert rec is not None

    from db.models.evidence import CSE, Submission

    # Create other entity and submission so FK constraints succeed
    other_cse = CSE(id="CSE-ROGUE-99", code="CSE-ROGUE-99", name="Rogue CSE")
    session.add(other_cse)
    other_sub = Submission(
        id="SUB-OTHER-99",
        entity_id="CSE-BANK-01",
        period_start=sub.period_start,
        period_end=sub.period_end,
        manifest_json="{}",
        status="committed",
    )
    session.add(other_sub)
    session.flush()

    # Mutate record scope to a different entity
    original_entity = rec.entity_id
    rec.entity_id = "CSE-ROGUE-99"
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "unresolvable_or_cross_scope_record" in reasons

    # Restore entity and mutate submission
    rec.entity_id = original_entity
    rec.submission_id = "SUB-OTHER-99"
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "unresolvable_or_cross_scope_record" in reasons


def test_citation_negative_removed_required_citation(eval_env):
    """Factual adverse finding without citations must be flagged as missing citations."""
    session, sub, findings, _ = eval_env
    f = next(
        f
        for f in findings
        if f.evidence_state in ("potential_concern", "contradictory", "contradicted")
        and f.primary_object_type not in ("source", "submission")
    )
    f.supporting_sources_json = json.dumps([])
    session.flush()

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "missing_required_citations" in reasons


def test_citation_negative_tampered_source_bytes(eval_env):
    """Tampering with uploaded file bytes on disk must be detected."""
    session, sub, findings, _ = eval_env
    assert len(sub.files) > 0
    target_file = sub.files[0]
    file_path = Path(target_file.storage_path)
    assert file_path.exists()

    # Tamper with the raw bytes on disk
    file_path.write_bytes(b"tampered_corrupted_payload_bytes_12345")

    broken = validate_citations(findings, session, sub)
    assert len(broken) >= 1
    reasons = {b.get("reason") for b in broken}
    assert "uploaded_file_digest_mismatch" in reasons


def test_broken_citations_fails_scenario_evaluation(eval_scenario, monkeypatch):
    """Proves broken citations cause run_scenario_evaluation to return FAIL."""
    import evaluation.validate_scenarios as vs
    from evaluation.validate_scenarios import run_scenario_evaluation

    monkeypatch.setattr(
        vs,
        "validate_citations",
        lambda findings, db, sub: [
            {"finding_id": "mock-f-1", "reason": "citation_provenance_mismatch"}
        ],
    )

    res = run_scenario_evaluation(eval_scenario)
    assert res["status"] == "FAIL"
    assert len(res["broken_citations"]) == 1
    assert "Broken citations: 1" in res["explanation"]
