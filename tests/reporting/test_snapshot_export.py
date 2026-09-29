"""Tests for frozen assessment report snapshots, immutability, provenance, and HTML rendering."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import create_user_session, hash_password
from db.models.access import User
from db.models.evidence import CSE, Submission
from db.models.reports import AssessmentReport
from db.models.review import ReviewDecision
from packages.analytics.service import AnalysisService
from packages.reporting.manifest import ChecksumManifest, compute_sha256_bytes
from packages.reporting.render import HTMLReportRenderer
from packages.reporting.snapshot import ReportSnapshotBuilder
from tests.conftest import authenticate_user
from tests.scenario_adapter import attach_scenario


@pytest.fixture
def assessment_fixture_data():
    path = Path("synthetic/scenarios/assessment.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_snapshot_immutability_against_later_decisions(
    db_session: Session, assessment_fixture_data
):
    """Verifies that later decisions recorded after decision_cutoff_time do NOT mutate snapshot."""
    # 1. Seed CSE and User
    cse = CSE(id="CSE-SNAP-01", code="CSE-SNAP-01", name="Snapshot Test Bank")
    user = User(
        id="lead_examiner",
        username="lead_examiner",
        password_hash=hash_password("Pass123!"),
        role="examiner",
        entity_scope='["CSE-SNAP-01"]',
    )
    db_session.add_all([cse, user])
    db_session.commit()

    sub = Submission(
        id="SUB-SNAP-01",
        entity_id="CSE-SNAP-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_fixture_data)
    db_session.add(sub)
    db_session.commit()

    # 2. Run Assessment
    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id="SUB-SNAP-01",
        cse_id="CSE-SNAP-01",
        semantic_mode="off",
    )
    findings = service.list_findings(run_id=run.id)
    assert len(findings) > 0
    target_finding = findings[0]

    # 3. Record Initial Decision before Cutoff
    t_initial = datetime.fromisoformat("2026-09-10T10:00:00+00:00")
    d1 = ReviewDecision(
        finding_id=target_finding.id,
        entity_id="CSE-SNAP-01",
        reviewer_id="lead_examiner",
        reviewer_username="lead_examiner",
        state="substantiated",
        rationale="Initial finding substantiated based on server logs.",
        cited_evidence_ids_json='["REC-01"]',
        version=1,
        created_at=t_initial,
    )
    db_session.add(d1)
    db_session.commit()

    # 4. Freeze Snapshot at Cutoff t_cutoff
    t_cutoff = datetime.fromisoformat("2026-09-10T12:00:00+00:00")
    builder = ReportSnapshotBuilder(db_session)
    frozen_snapshot = builder.build_snapshot(
        run_id=run.id,
        entity_id="CSE-SNAP-01",
        decision_cutoff_time=t_cutoff,
    )

    finding_decisions = frozen_snapshot["examiner_decisions"]["finding_decisions"]
    assert len(finding_decisions) == 1
    assert finding_decisions[0]["state"] == "substantiated"
    assert (
        finding_decisions[0]["rationale"] == "Initial finding substantiated based on server logs."
    )

    # 5. Record Later Decision AFTER Cutoff
    t_later = datetime.fromisoformat("2026-09-15T10:00:00+00:00")
    d2 = ReviewDecision(
        finding_id=target_finding.id,
        entity_id="CSE-SNAP-01",
        reviewer_id="lead_examiner",
        reviewer_username="lead_examiner",
        state="not_substantiated",
        rationale="Overridden later with new explanations.",
        cited_evidence_ids_json='["REC-02"]',
        superseded_decision_id=d1.id,
        version=2,
        created_at=t_later,
    )
    db_session.add(d2)
    db_session.commit()

    # 6. Re-evaluate snapshot with the frozen cutoff: must remain unchanged!
    rebuilt_snapshot = builder.build_snapshot(
        run_id=run.id,
        entity_id="CSE-SNAP-01",
        decision_cutoff_time=t_cutoff,
    )

    assert rebuilt_snapshot["examiner_decisions"] == frozen_snapshot["examiner_decisions"]
    rebuilt_decisions = rebuilt_snapshot["examiner_decisions"]["finding_decisions"]
    assert len(rebuilt_decisions) == 1
    assert rebuilt_decisions[0]["state"] == "substantiated"
    assert rebuilt_decisions[0]["decision_id"] == d1.id


def test_html_rendering_escapes_xss_and_contains_no_external_resources(
    db_session: Session, assessment_fixture_data
):
    """Verifies that hostile XSS payloads are strictly escaped and no external CDNs exist."""
    cse = CSE(id="CSE-XSS-01", code="CSE-XSS-01", name="Security Test Bank")
    db_session.add(cse)
    db_session.commit()

    sub = Submission(
        id="SUB-XSS-01",
        entity_id="CSE-XSS-01",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    attach_scenario(sub, assessment_fixture_data)
    db_session.add(sub)
    db_session.commit()

    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id="SUB-XSS-01",
        cse_id="CSE-XSS-01",
        semantic_mode="off",
    )

    # Inject hostile XSS payload into a decision rationale and notes
    xss_payload = '<script>alert("PWNED")</script><img src=x onerror=alert(1)>'
    builder = ReportSnapshotBuilder(db_session)
    snapshot = builder.build_snapshot(
        run_id=run.id,
        entity_id="CSE-XSS-01",
        notes=xss_payload,
    )

    # Manually inject into a finding observation for thoroughness
    if snapshot["findings"]:
        snapshot["findings"][0]["observation"] = f"Observed anomaly: {xss_payload}"

    manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=json.dumps(snapshot).encode("utf-8"),
        html_bytes=b"dummy",
        input_file_digests={},
        rule_version="rules-v1",
        policy_version="demo-v1",
    )

    renderer = HTMLReportRenderer()
    rendered_html = renderer.render(snapshot, manifest)

    # 1. Assert unescaped tag is NOT present
    assert "<script>alert" not in rendered_html
    assert "<img src=x" not in rendered_html

    # 2. Assert properly escaped entity is present
    assert "&lt;script&gt;alert" in rendered_html
    assert "&lt;img src=x" in rendered_html

    # 3. Assert zero remote font or CDN imports
    assert "fonts.googleapis.com" not in rendered_html
    assert "cdnjs.cloudflare.com" not in rendered_html
    assert "cdn.jsdelivr.net" not in rendered_html


def test_cross_entity_report_authorization(client: TestClient, db_session: Session):
    """Verifies that an examiner from CSE-A cannot access or download reports for CSE-B."""
    # User from CSE-A
    user_a = User(
        id="user_a_id",
        username="examiner_a",
        password_hash=hash_password("Pass123!"),
        role="examiner",
        entity_scope='["CSE-BANK-01"]',
    )
    db_session.add(user_a)

    # Seed submission and run for CSE-FINTECH-02
    sub_b = Submission(
        id="SUB-B-001",
        entity_id="CSE-FINTECH-02",
        period_start=datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        period_end=datetime.fromisoformat("2026-08-31T23:59:59+00:00"),
        manifest_json="{}",
        status="committed",
    )
    db_session.add(sub_b)
    db_session.commit()

    from db.models.assessment import AnalysisRun

    run_b = AnalysisRun(
        id="run-b-001",
        submission_id="SUB-B-001",
        entity_id="CSE-FINTECH-02",
        status="completed",
        input_hash="hash_b",
        cutoff_time=datetime.now(timezone.utc),
    )
    db_session.add(run_b)
    db_session.commit()

    # Report belonging to CSE-FINTECH-02
    report_b = AssessmentReport(
        id="rep-entity-b-001",
        run_id="run-b-001",
        entity_id="CSE-FINTECH-02",
        created_by="other_examiner",
        decision_cutoff_time=datetime.now(timezone.utc),
        status="completed",
        report_schema_version="v1.0",
        snapshot_json="{}",
        html_content="<html><body>CSE B Report</body></html>",
        checksum_manifest_json="{}",
    )
    db_session.add(report_b)
    db_session.commit()

    db_session.commit()

    token_a, _, _ = create_user_session(user_a, db_session)
    client.cookies.set("sat_session", token_a)

    # 1. Attempt to GET report metadata
    res_get = client.get(f"/api/v1/reports/{report_b.id}")
    assert res_get.status_code == 403

    # 2. Attempt to download HTML
    res_html = client.get(f"/api/v1/reports/{report_b.id}/html")
    assert res_html.status_code == 403

    # 3. Attempt to download JSON
    res_json = client.get(f"/api/v1/reports/{report_b.id}/json")
    assert res_json.status_code == 403

    # 4. Attempt to download bundle
    res_bundle = client.get(f"/api/v1/reports/{report_b.id}/bundle")
    assert res_bundle.status_code == 403


def test_checksum_manifest_verification_and_tamper_detection():
    """Verifies ChecksumManifest validates authentic artifacts and detects bit changes."""
    snapshot_bytes = b'{"report_id": "rep-test", "status": "completed"}'
    html_bytes = b"<!DOCTYPE html><html><body>Test Report</body></html>"
    source_digests = {"submission.json": compute_sha256_bytes(b"raw submission data")}

    manifest = ChecksumManifest.build_manifest(
        snapshot_bytes=snapshot_bytes,
        html_bytes=html_bytes,
        input_file_digests=source_digests,
        rule_version="rules-v1",
        policy_version="demo-v1",
    )

    # 1. Authentic verification
    snapshot_hash = manifest["components"]["snapshot_json"]["sha256"]
    assert ChecksumManifest.verify_artifact(snapshot_bytes, snapshot_hash) is True

    html_hash = manifest["components"]["assessment_html"]["sha256"]
    assert ChecksumManifest.verify_artifact(html_bytes, html_hash) is True

    # 2. Tampered verification (flip one byte)
    tampered_bytes = snapshot_bytes + b" "
    assert ChecksumManifest.verify_artifact(tampered_bytes, snapshot_hash) is False


def test_report_generation_with_real_uploaded_files(client: TestClient, db_session: Session):
    """End-to-end acceptance test: Real uploads through endpoints -> report creation (201)

    Verifies:
    1. Import all 5 declared sources from world_a_complete fixture through submission endpoints.
    2. Accurate file metadata: filenames, source identity, byte sizes, counts, hashes.
    3. Hashes match uploaded bytes computed independently with hashlib.sha256.
    4. Downloads of HTML, JSON, manifest, and ZIP bundle succeed (200).
    5. Artifact checksums verify.
    6. Report immutability against decisions added after cutoff.
    """
    # 1. Examiner user for CSE-BANK-01
    user = User(
        id="examiner_upload_test",
        username="examiner_upload_test",
        password_hash=hash_password("Pass123!"),
        role="examiner",
        entity_scope='["CSE-BANK-01"]',
    )
    db_session.add(user)
    db_session.commit()

    headers = authenticate_user(client, user, db_session)
    client.headers.update(headers)

    # 2. Load manifest from world_a_complete fixture
    world_dir = Path("synthetic/fixtures/world_a_complete/submission")
    manifest_data = json.loads((world_dir / "manifest.json").read_text(encoding="utf-8"))

    # 3. Create Draft Submission via API
    sub_res = client.post("/api/v1/submissions", json=manifest_data)
    assert sub_res.status_code == 201, f"Failed to create submission: {sub_res.text}"
    sub = sub_res.json()
    sub_id = sub["id"]

    # 4. Upload all 5 declared sources and compute independent byte hashes
    file_map = {
        "src-assets-csv": ("assets.csv", "text/csv"),
        "src-alerts-csv": ("alerts.csv", "text/csv"),
        "src-cases-json": ("cases.json", "application/json"),
        "src-links-json": ("case_alert_links.json", "application/json"),
        "src-coverage-json": ("coverage_observations.json", "application/json"),
    }

    uploaded_files_info = {}
    for source_id, (fname, ctype) in file_map.items():
        raw_bytes = (world_dir / fname).read_bytes()
        expected_hash = hashlib.sha256(raw_bytes).hexdigest()
        uploaded_files_info[source_id] = {
            "filename": fname,
            "bytes": raw_bytes,
            "byte_size": len(raw_bytes),
            "sha256_hash": expected_hash,
        }

        upload_res = client.post(
            f"/api/v1/submissions/{sub_id}/files",
            data={"source_id": source_id},
            files={"file": (fname, raw_bytes, ctype)},
        )
        assert upload_res.status_code == 200, f"Upload failed for {source_id}: {upload_res.text}"
        meta = upload_res.json()
        assert meta["sha256_hash"] == expected_hash
        assert meta["byte_size"] == len(raw_bytes)

    # 5. Validate Evidence
    val_res = client.post(f"/api/v1/submissions/{sub_id}/validate")
    assert val_res.status_code == 200, f"Validation failed: {val_res.text}"
    quality = val_res.json()
    assert quality["accepted_count"] == 11
    assert quality["rejected_count"] == 0

    # 6. Commit Submission
    idemp_key = f"idemp-test-upload-{sub_id}"
    commit_res = client.post(
        f"/api/v1/submissions/{sub_id}/commit",
        json={"idempotency_key": idemp_key},
    )
    assert commit_res.status_code == 200, f"Commit failed: {commit_res.text}"

    # 7. Run Assessment
    service = AnalysisService(db_session)
    run = service.run_assessment(
        submission_id=sub_id,
        cse_id="CSE-BANK-01",
        semantic_mode="off",
    )
    assert run.status == "completed"

    findings = service.list_findings(run_id=run.id)
    assert len(findings) > 0
    target_finding = findings[0]

    # Add initial decision before cutoff
    t_cutoff = datetime.now(timezone.utc)
    dec_res = client.post(
        f"/api/v1/findings/{target_finding.id}/decisions",
        json={
            "state": "substantiated",
            "rationale": "Substantiated with real uploaded logs.",
            "cited_evidence_ids": [],
        },
    )
    assert dec_res.status_code == 201

    # 8. Create Report via POST /api/v1/reports -> Must return 201
    rep_res = client.post(
        "/api/v1/reports",
        json={
            "run_id": run.id,
            "decision_cutoff_time": t_cutoff.isoformat(),
            "notes": "Report with real uploaded files",
        },
    )
    assert rep_res.status_code == 201, f"Report creation failed: {rep_res.text}"
    rep_data = rep_res.json()
    report_id = rep_data["id"]

    # 9. Verify JSON snapshot includes accurate file names, source identity, byte sizes, counts, hashes
    res_json = client.get(f"/api/v1/reports/{report_id}/json")
    assert res_json.status_code == 200
    snapshot = res_json.json()
    files_in_snapshot = snapshot["submission"]["files"]
    assert len(files_in_snapshot) == 5

    # Check against independently calculated raw byte hashes and sizes
    for f in files_in_snapshot:
        src_id = f["source_id"]
        assert src_id in uploaded_files_info
        expected = uploaded_files_info[src_id]

        assert f["original_filename"] == expected["filename"]
        assert f["byte_size"] == expected["byte_size"]
        assert f["sha256_hash"] == expected["sha256_hash"]
        assert f["actual_row_count"] > 0
        assert f["declared_row_count"] > 0
        # Both actual and declared counts must be distinguished and accurate
        assert f["actual_row_count"] == f["declared_row_count"]

    # 10. Verify HTML download (200)
    res_html = client.get(f"/api/v1/reports/{report_id}/html")
    assert res_html.status_code == 200
    html_text = res_html.text
    for expected in uploaded_files_info.values():
        assert expected["filename"] in html_text
        assert expected["sha256_hash"] in html_text

    # 11. Verify Manifest download (200) and verify artifact hashes against independent bytes
    res_manifest = client.get(f"/api/v1/reports/{report_id}/manifest")
    assert res_manifest.status_code == 200
    manifest = res_manifest.json()

    # Verify source submissions in manifest match independently computed raw file hashes
    for expected in uploaded_files_info.values():
        assert manifest["source_submissions"][expected["filename"]] == expected["sha256_hash"]

    # Verify report artifacts match manifest checksums
    assert ChecksumManifest.verify_artifact(
        res_json.content, manifest["components"]["snapshot_json"]["sha256"]
    )
    assert ChecksumManifest.verify_artifact(
        res_html.content, manifest["components"]["assessment_html"]["sha256"]
    )

    # 12. Verify ZIP bundle download (200)
    res_bundle = client.get(f"/api/v1/reports/{report_id}/bundle")
    assert res_bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_bundle.content)) as zf:
        names = zf.namelist()
        assert "assessment.html" in names
        assert "snapshot.json" in names
        assert "manifest.json" in names
        assert "README.txt" in names

        # Bundle contents must match the downloaded artifacts
        assert zf.read("snapshot.json") == res_json.content
        assert zf.read("assessment.html") == res_html.content
        assert zf.read("manifest.json") == res_manifest.content

    # 13. Verify later decision does not change frozen report
    late_dec_res = client.post(
        f"/api/v1/findings/{target_finding.id}/decisions",
        json={
            "state": "not_substantiated",
            "rationale": "Overridden after frozen report was created.",
            "cited_evidence_ids": [],
            "expected_version": 1,
        },
    )
    assert late_dec_res.status_code == 201

    # Re-download report JSON: must remain identical to frozen snapshot
    res_json_after = client.get(f"/api/v1/reports/{report_id}/json")
    assert res_json_after.status_code == 200
    snapshot_after = res_json_after.json()
    assert snapshot_after == snapshot


def test_expected_failure_leaves_no_partially_successful_report(
    client: TestClient, db_session: Session
):
    """Verifies that an expected failure during report creation leaves no partially successful report."""
    user = User(
        id="examiner_fail_test",
        username="examiner_fail_test",
        password_hash=hash_password("Pass123!"),
        role="examiner",
        entity_scope='["CSE-BANK-01"]',
    )
    db_session.add(user)
    db_session.commit()

    headers = authenticate_user(client, user, db_session)
    client.headers.update(headers)

    # Count reports before
    reports_before = db_session.execute(select(AssessmentReport)).scalars().all()
    count_before = len(reports_before)

    # Request report for non-existent run ID -> returns 404
    res = client.post(
        "/api/v1/reports",
        json={"run_id": "non-existent-run-id-99999"},
    )
    assert res.status_code == 404

    # Count reports after: must not increase
    reports_after = db_session.execute(select(AssessmentReport)).scalars().all()
    assert len(reports_after) == count_before
