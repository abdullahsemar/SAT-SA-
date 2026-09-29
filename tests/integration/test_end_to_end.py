"""Genuine Persisted-Data End-to-End Lifecycle Integration Test.

Implements the complete 20-step lifecycle required by Phase B (B3, B4, B5, B6):
1. Create synthetic entity and test user using supported setup mechanisms.
2. Authenticate through the actual login endpoint.
3. Create a submission using a valid manifest.
4. Upload actual JSON/CSV file bytes through the upload endpoint.
5. Validate and inspect quality results.
6. Verify draft assessment protection (409 Conflict before commit).
7. Commit the submission.
8. Verify post-commit mutation protection (409 Conflict on file upload after commit).
9. Run assessment analysis.
10. Retrieve findings and check expected content.
11. Resolve citations to raw/normalized records.
12. Retrieve evidence chains for objects.
13. Read persisted semantic evidence strictly read-only.
14. Create a saved review portfolio with budget allocation.
15. Review a genuine unflagged item without inventing a finding.
16. Save a finding determination separately.
17. File a local evidence request against an item without a finding.
18. Generate a frozen assessment report.
19. Download HTML, JSON, manifest, and ZIP bundle; verify byte hashes and metadata.
20. Save a later examiner decision after cutoff.
21. Verify report immutability (existing report bytes and decision state unchanged).
22. Verify unauthorized cross-entity report access is rejected (403 Forbidden).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.auth import hash_password
from db.models.access import User
from db.models.evidence import CSE
from packages.reporting.manifest import ChecksumManifest


def test_genuine_persisted_data_lifecycle_regression(client: TestClient, db_session: Session):
    # -------------------------------------------------------------------------
    # 1. Create synthetic entity and test user
    # -------------------------------------------------------------------------
    cse_id = "CSE-BANK-01"
    # Ensure entity exists
    if not db_session.get(CSE, cse_id):
        db_session.add(CSE(id=cse_id, code=cse_id, name="First National Bank CSE"))
        db_session.commit()

    examiner_username = "lead_examiner_e2e"
    examiner_password = "E2EExaminerPass123!"
    examiner_user = User(
        id="usr-e2e-examiner-01",
        username=examiner_username,
        password_hash=hash_password(examiner_password),
        role="examiner",
        entity_scope=json.dumps([cse_id]),
        is_active=True,
    )
    db_session.add(examiner_user)
    db_session.commit()

    # -------------------------------------------------------------------------
    # 2. Authenticate through the actual login endpoint
    # -------------------------------------------------------------------------
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": examiner_username, "password": examiner_password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    user_profile = login_resp.json()
    assert user_profile["username"] == examiner_username
    assert user_profile["role"] == "examiner"
    assert cse_id in user_profile["entity_scope"]
    csrf_token = user_profile.get("csrf_token")
    assert csrf_token is not None

    auth_headers = {"X-CSRF-Token": csrf_token}

    # -------------------------------------------------------------------------
    # 3. Create a submission using a valid manifest
    # -------------------------------------------------------------------------
    manifest_payload = {
        "manifest_version": "1.0.0",
        "entity_id": cse_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "source_timezone": "UTC",
        "sources": [
            {
                "source_id": "src-cases",
                "record_type": "cases",
                "declared_row_count": 3,
                "export_scope": "Full incident case export",
                "lineage": "SIEM Case Management",
                "sampling_method": "full_population",
            },
            {
                "source_id": "src-actions",
                "record_type": "investigation_actions",
                "declared_row_count": 3,
                "export_scope": "SOAR action telemetry",
                "lineage": "SOAR Playbook Engine",
                "sampling_method": "full_population",
            },
            {
                "source_id": "src-esc",
                "record_type": "escalations",
                "declared_row_count": 1,
                "export_scope": "Authoritative PagerDuty export",
                "lineage": "PagerDuty",
                "sampling_method": "full_population",
            },
            {
                "source_id": "src-assets",
                "record_type": "assets",
                "declared_row_count": 2,
                "export_scope": "Core server inventory",
                "lineage": "Enterprise CMDB",
                "sampling_method": "full_population",
            },
            {
                "source_id": "src-claims",
                "record_type": "reported_claims",
                "declared_row_count": 1,
                "export_scope": "Self-reported supervisory metrics",
                "lineage": "Executive Dashboard",
                "sampling_method": "full_population",
            },
        ],
    }

    create_sub_resp = client.post(
        "/api/v1/submissions", json=manifest_payload, headers=auth_headers
    )
    assert create_sub_resp.status_code == 201, f"Create sub failed: {create_sub_resp.text}"
    sub_data = create_sub_resp.json()
    submission_id = sub_data["id"]
    assert sub_data["status"] == "draft"

    # -------------------------------------------------------------------------
    # 4. Upload actual JSON file bytes through the upload endpoint
    # -------------------------------------------------------------------------
    # File 1: Cases
    # CASE-01: CRITICAL, compliant (closed in 30m with required artifacts)
    # CASE-02: CRITICAL, non-compliant (28h duration > 4h SLA, no escalation)
    # CASE-03: MEDIUM, compliant (closed in 30m, unflagged control candidate)
    cases_data = [
        {
            "native_id": "CASE-01",
            "case_id": "CASE-01",
            "severity": "CRITICAL",
            "status": "CLOSED",
            "created_at": "2026-08-05T10:00:00Z",
            "closed_at": "2026-08-05T10:30:00Z",
            "root_cause": "Malware payload isolated from endpoint",
            "resolution": "RESOLVED",
        },
        {
            "native_id": "CASE-02",
            "case_id": "CASE-02",
            "severity": "CRITICAL",
            "status": "CLOSED",
            "created_at": "2026-08-10T14:00:00Z",
            "closed_at": "2026-08-11T18:00:00Z",
            "root_cause": "Ransomware outbreak breached perimeter",
            "resolution": "CONTAINED",
        },
        {
            "native_id": "CASE-03",
            "case_id": "CASE-03",
            "severity": "MEDIUM",
            "status": "CLOSED",
            "created_at": "2026-08-12T09:00:00Z",
            "closed_at": "2026-08-12T09:30:00Z",
            "resolution": "FALSE_POSITIVE",
        },
    ]
    cases_bytes = json.dumps(cases_data).encode("utf-8")

    # File 2: Actions
    actions_data = [
        {
            "native_id": "ACT-01-ISO",
            "action_id": "ACT-01-ISO",
            "case_id": "CASE-01",
            "action_type": "HOST_ISOLATION",
            "actor": "secops-tier2",
            "timestamp": "2026-08-05T10:10:00Z",
            "artifact_hash": "a1b2c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596",
        },
        {
            "native_id": "ACT-01-TRIAGE",
            "action_id": "ACT-01-TRIAGE",
            "case_id": "CASE-01",
            "action_type": "FORENSIC_TRIAGE",
            "actor": "secops-tier2",
            "timestamp": "2026-08-05T10:15:00Z",
            "artifact_hash": "b2c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596a1",
        },
        {
            "native_id": "ACT-02-TRIAGE",
            "action_id": "ACT-02-TRIAGE",
            "case_id": "CASE-02",
            "action_type": "FORENSIC_TRIAGE",
            "actor": "secops-tier1",
            "timestamp": "2026-08-10T15:00:00Z",
            "artifact_hash": "c3d4e5f607182930415263748596a1b2c3d4e5f607182930415263748596a1b2",
        },
    ]
    actions_bytes = json.dumps(actions_data).encode("utf-8")

    # File 3: Escalations
    # Only CASE-01 was escalated; CASE-02 was not escalated within 30 min SLA
    escalations_data = [
        {
            "native_id": "ESC-01",
            "escalation_id": "ESC-01",
            "case_id": "CASE-01",
            "escalation_type": "PAGERDUTY",
            "escalation_level": "TIER_3",
            "notified_party": "oncall-lead@bank.internal",
            "timestamp": "2026-08-05T10:05:00Z",
        }
    ]
    escalations_bytes = json.dumps(escalations_data).encode("utf-8")

    # File 4: Assets
    assets_data = [
        {
            "native_id": "AST-01",
            "asset_id": "AST-01",
            "hostname": "core01.bank.internal",
            "criticality": "CRITICAL",
            "agent_status": "HEALTHY",
            "last_heartbeat": "2026-08-31T23:50:00Z",
        },
        {
            "native_id": "AST-02",
            "asset_id": "AST-02",
            "hostname": "app02.bank.internal",
            "criticality": "HIGH",
            "agent_status": "HEALTHY",
            "last_heartbeat": "2026-08-31T23:45:00Z",
        },
    ]
    assets_bytes = json.dumps(assets_data).encode("utf-8")

    # File 5: Reported Claims
    claims_data = [
        {
            "native_id": "CLM-01",
            "claim_id": "CLM-01",
            "metric_name": "incident_sla_compliance_pct",
            "period": "2026-08",
            "metric_value": 99.0,
        }
    ]
    claims_bytes = json.dumps(claims_data).encode("utf-8")

    uploads = [
        ("src-cases", "cases.json", cases_bytes),
        ("src-actions", "investigation_actions.json", actions_bytes),
        ("src-esc", "escalations.json", escalations_bytes),
        ("src-assets", "assets.json", assets_bytes),
        ("src-claims", "reported_claims.json", claims_bytes),
    ]

    for source_id, filename, file_bytes in uploads:
        up_resp = client.post(
            f"/api/v1/submissions/{submission_id}/files",
            data={"source_id": source_id},
            files={"file": (filename, file_bytes, "application/json")},
            headers=auth_headers,
        )
        assert up_resp.status_code == 200, (
            f"Upload failed for {source_id} ({filename}): {up_resp.text}"
        )
        f_meta = up_resp.json()
        assert f_meta["source_id"] == source_id
        assert f_meta["original_filename"] == filename
        assert f_meta["byte_size"] == len(file_bytes)
        assert f_meta["sha256_hash"] == hashlib.sha256(file_bytes).hexdigest()

    # -------------------------------------------------------------------------
    # 5. Validate and inspect quality results
    # -------------------------------------------------------------------------
    val_resp = client.post(f"/api/v1/submissions/{submission_id}/validate", headers=auth_headers)
    assert val_resp.status_code == 200, f"Validation failed: {val_resp.text}"
    quality_data = val_resp.json()
    assert quality_data["accepted_count"] == 10  # 3 + 3 + 1 + 2 + 1
    assert quality_data["quarantined_count"] == 0

    # -------------------------------------------------------------------------
    # 6. Confirm draft assessment protection (409 before commit)
    # -------------------------------------------------------------------------
    precommit_analysis_resp = client.post(
        "/api/v1/analysis-runs",
        json={"submission_id": submission_id, "semantic_mode": "auto"},
        headers=auth_headers,
    )
    assert precommit_analysis_resp.status_code == 409, "Uncommitted submission must return 409"

    # -------------------------------------------------------------------------
    # 7. Commit the submission
    # -------------------------------------------------------------------------
    commit_resp = client.post(
        f"/api/v1/submissions/{submission_id}/commit",
        json={"idempotency_key": "IDEM-LIFECYCLE-01"},
        headers=auth_headers,
    )
    assert commit_resp.status_code == 200, f"Commit failed: {commit_resp.text}"
    committed_sub = commit_resp.json()
    assert committed_sub["status"] == "committed"
    assert len(committed_sub["files"]) == 5

    # -------------------------------------------------------------------------
    # 8. Confirm post-commit mutation protection (409 on upload after commit)
    # -------------------------------------------------------------------------
    postcommit_up_resp = client.post(
        f"/api/v1/submissions/{submission_id}/files",
        data={"source_id": "src-cases"},
        files={"file": ("extra_cases.json", b"[]", "application/json")},
        headers=auth_headers,
    )
    assert postcommit_up_resp.status_code == 409, (
        "Upload after commit must be rejected with 409 Conflict"
    )

    # -------------------------------------------------------------------------
    # 9. Run assessment
    # -------------------------------------------------------------------------
    analysis_resp = client.post(
        "/api/v1/analysis-runs",
        json={"submission_id": submission_id, "semantic_mode": "auto"},
        headers=auth_headers,
    )
    assert analysis_resp.status_code == 201, f"Analysis failed: {analysis_resp.text}"
    run_data = analysis_resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "completed"

    # -------------------------------------------------------------------------
    # 10. Retrieve findings and check expected content
    # -------------------------------------------------------------------------
    findings_resp = client.get(f"/api/v1/findings?run_id={run_id}", headers=auth_headers)
    assert findings_resp.status_code == 200
    findings = findings_resp.json()
    assert len(findings) >= 2

    # Expect contradiction on CLM-01 (66.7% upper bound < 99% claimed)
    kpi_findings = [f for f in findings if f["rule_id"] == "POL-KPI-004"]
    assert len(kpi_findings) == 1
    kpi_finding = kpi_findings[0]
    assert kpi_finding["primary_object_id"] == "CLM-01"
    assert kpi_finding["evidence_state"] in ("contradictory", "contradicted")

    # Expect overdue escalation on CASE-02 (28h case, 30m escalation SLA not met)
    esc_findings = [
        f for f in findings if f["rule_id"] == "POL-ESC-002" and f["primary_object_id"] == "CASE-02"
    ]
    assert len(esc_findings) == 1
    esc_finding = esc_findings[0]
    assert esc_finding["evidence_state"] == "potential_concern"

    # Compliant case CASE-01 must NOT have adverse finding
    case1_adverse = [
        f
        for f in findings
        if f["primary_object_id"] == "CASE-01"
        and f["evidence_state"] in ("potential_concern", "contradicted", "contradictory")
    ]
    assert len(case1_adverse) == 0, "CASE-01 must not have adverse findings"

    # -------------------------------------------------------------------------
    # 11. Resolve citations to the correct raw/normalized records
    # -------------------------------------------------------------------------
    rec_resp = client.get("/api/v1/evidence/records/CASE-01", headers=auth_headers)
    assert rec_resp.status_code == 200, f"Record resolution failed: {rec_resp.text}"
    rec_data = rec_resp.json()
    assert rec_data["native_id"] == "CASE-01"
    assert rec_data["entity_id"] == cse_id
    assert rec_data["source_id"] == "src-cases"
    assert rec_data["raw_payload"]["severity"] == "CRITICAL"

    # -------------------------------------------------------------------------
    # 12. Retrieve evidence chains for the correct objects
    # -------------------------------------------------------------------------
    chain_resp = client.get(
        f"/api/v1/evidence/chains/CASE-01?submission_id={submission_id}", headers=auth_headers
    )
    assert chain_resp.status_code == 200, f"Evidence chain failed: {chain_resp.text}"
    chain_data = chain_resp.json()
    assert chain_data["object_id"] == "CASE-01"
    assert len(chain_data["timeline"]) >= 1

    # -------------------------------------------------------------------------
    # 13. Read persisted semantic evidence
    # -------------------------------------------------------------------------
    sem_resp = client.get(
        f"/api/v1/findings/{esc_finding['finding_id']}/similar-passages", headers=auth_headers
    )
    assert sem_resp.status_code == 200
    sem_data = sem_resp.json()
    assert sem_data["finding_id"] == esc_finding["finding_id"]
    assert sem_data["status"] in ("completed", "disabled", "not_computed")

    # -------------------------------------------------------------------------
    # 14. Create a saved review portfolio
    # -------------------------------------------------------------------------
    port_resp = client.post(
        "/api/v1/review-portfolios",
        json={
            "run_id": run_id,
            "max_items": 5,
            "strata_allocation": {"targeted": 2, "control": 1, "exploratory": 1},
            "seed": 42,
        },
        headers=auth_headers,
    )
    assert port_resp.status_code == 201, f"Portfolio creation failed: {port_resp.text}"
    portfolio_data = port_resp.json()
    portfolio_id = portfolio_data["id"]
    items = portfolio_data["items"]
    assert len(items) > 0

    # Ensure native IDs remain intact in portfolio items
    control_items = [it for it in items if it["stratum"] == "control"]
    targeted_items = [it for it in items if it["stratum"] == "targeted"]
    assert len(control_items) >= 1, "Must contain at least 1 genuine unflagged control item"
    assert len(targeted_items) >= 1, "Must contain at least 1 flagged targeted item"

    unflagged_ctrl = control_items[0]
    assert unflagged_ctrl["finding_id"] is None, "Control item must not be tied to a finding"
    assert any(cid in unflagged_ctrl["unit_id"] for cid in ("CASE-01", "CASE-03")), (
        "Control item must be genuine unflagged case"
    )

    # Verify portfolio order and reasons remain stable when reopened
    reopen_resp = client.get(f"/api/v1/review-portfolios/{portfolio_id}", headers=auth_headers)
    assert reopen_resp.status_code == 200
    reopened_items = reopen_resp.json()["items"]
    assert [it["id"] for it in items] == [it["id"] for it in reopened_items]
    assert [it["marginal_reasons"] for it in items] == [
        it["marginal_reasons"] for it in reopened_items
    ]

    # -------------------------------------------------------------------------
    # 15. Review a genuine unflagged item without inventing a finding
    # -------------------------------------------------------------------------
    item_dec_resp = client.post(
        f"/api/v1/review-items/{unflagged_ctrl['id']}/decisions",
        json={
            "state": "reviewed_no_concern",
            "rationale": "Examiner verified case resolved compliant without requiring escalation.",
            "cited_evidence_ids": [],
        },
        headers=auth_headers,
    )
    assert item_dec_resp.status_code == 201
    item_dec = item_dec_resp.json()
    assert item_dec["state"] == "reviewed_no_concern"
    assert item_dec["review_item_id"] == unflagged_ctrl["id"]

    # -------------------------------------------------------------------------
    # 16. Save a finding determination separately
    # -------------------------------------------------------------------------
    find_dec_resp = client.post(
        f"/api/v1/findings/{esc_finding['finding_id']}/decisions",
        json={
            "state": "substantiated",
            "rationale": "Overdue escalation breach substantiated. <script>alert('xss_test')</script>",
            "cited_evidence_ids": [],
        },
        headers=auth_headers,
    )
    assert find_dec_resp.status_code == 201
    find_dec = find_dec_resp.json()
    assert find_dec["state"] == "substantiated"
    pre_cutoff_decision_id = find_dec["id"]

    # -------------------------------------------------------------------------
    # 17. File a local evidence request against an item without a finding
    # -------------------------------------------------------------------------
    ev_req_resp = client.post(
        "/api/v1/evidence-requests",
        json={
            "review_item_id": unflagged_ctrl["id"],
            "missing_artifact": "analyst_shift_handover_log.pdf",
            "distinguishing_question": "Does shift handover note confirm resolution before shift end?",
            "responsible_owner": "SOC Tier 1 Lead",
            "due_date": "2026-09-30T17:00:00Z",
        },
        headers=auth_headers,
    )
    assert ev_req_resp.status_code == 201
    ev_req_data = ev_req_resp.json()
    assert ev_req_data["review_item_id"] == unflagged_ctrl["id"]
    assert ev_req_data["status"] == "open"

    # -------------------------------------------------------------------------
    # 18. Generate a frozen assessment report
    # -------------------------------------------------------------------------
    t_cutoff = datetime.now(timezone.utc)
    report_notes = "End-to-End verified report. <script>alert('xss_test')</script>"
    rep_create_resp = client.post(
        "/api/v1/reports",
        json={
            "run_id": run_id,
            "portfolio_id": portfolio_id,
            "decision_cutoff_time": t_cutoff.isoformat(),
            "notes": report_notes,
        },
        headers=auth_headers,
    )
    assert rep_create_resp.status_code == 201, f"Report creation failed: {rep_create_resp.text}"
    report_meta = rep_create_resp.json()
    report_id = report_meta["id"]

    # -------------------------------------------------------------------------
    # 19. Download HTML, JSON, manifest, and ZIP; verify contents and checksums
    # -------------------------------------------------------------------------
    # JSON Snapshot
    res_json = client.get(f"/api/v1/reports/{report_id}/json", headers=auth_headers)
    assert res_json.status_code == 200
    snapshot_json_bytes = res_json.content
    snapshot_data = res_json.json()
    assert snapshot_data["analysis_run"]["run_id"] == run_id
    assert snapshot_data["review_portfolio"]["portfolio_id"] == portfolio_id
    assert len(snapshot_data["evidence_requests"]) >= 1

    # Check input files in snapshot match original uploads
    input_files = snapshot_data["submission"]["files"]
    assert len(input_files) == 5
    source_names = {f["filename"] for f in input_files}
    assert "cases.json" in source_names
    assert "escalations.json" in source_names

    # HTML
    res_html = client.get(f"/api/v1/reports/{report_id}/html", headers=auth_headers)
    assert res_html.status_code == 200
    html_bytes = res_html.content
    html_text = res_html.text
    # Verify submitted markup is escaped in rendered HTML (XSS prevention)
    assert "<script>alert('xss_test')</script>" not in html_text
    assert "&lt;script&gt;alert(&#39;xss_test&#39;)&lt;/script&gt;" in html_text or (
        "xss_test" in html_text and "<script>" not in html_text
    )

    # Manifest
    res_man = client.get(f"/api/v1/reports/{report_id}/manifest", headers=auth_headers)
    assert res_man.status_code == 200
    manifest_data = res_man.json()
    # Verify standalone artifact hashes match manifest
    assert ChecksumManifest.verify_artifact(
        snapshot_json_bytes, manifest_data["components"]["snapshot_json"]["sha256"]
    )
    assert ChecksumManifest.verify_artifact(
        html_bytes, manifest_data["components"]["assessment_html"]["sha256"]
    )

    # Zip Bundle
    res_bundle = client.get(f"/api/v1/reports/{report_id}/bundle", headers=auth_headers)
    assert res_bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_bundle.content)) as zf:
        namelist = zf.namelist()
        assert "assessment.html" in namelist
        assert "snapshot.json" in namelist
        assert "manifest.json" in namelist
        assert "README.txt" in namelist
        # ZIP artifacts match standalone downloads exactly
        assert zf.read("assessment.html") == html_bytes
        assert zf.read("snapshot.json") == snapshot_json_bytes

    # -------------------------------------------------------------------------
    # 20. Save a later examiner decision after cutoff
    # -------------------------------------------------------------------------
    late_dec_resp = client.post(
        f"/api/v1/findings/{esc_finding['finding_id']}/decisions",
        json={
            "state": "not_applicable",
            "rationale": "Closed as out of scope in subsequent post-report audit.",
            "cited_evidence_ids": [],
            "expected_version": 2,
        },
        headers=auth_headers,
    )
    assert late_dec_resp.status_code == 201

    # -------------------------------------------------------------------------
    # 21. Verify existing report remains unchanged (bytes and decisions frozen)
    # -------------------------------------------------------------------------
    recheck_json = client.get(f"/api/v1/reports/{report_id}/json", headers=auth_headers)
    assert recheck_json.status_code == 200
    assert recheck_json.content == snapshot_json_bytes
    recheck_data = recheck_json.json()
    active_decisions = [
        d for d in recheck_data["examiner_decisions"]["finding_decisions"] if d["is_active"]
    ]
    assert len(active_decisions) == 1
    assert active_decisions[0]["decision_id"] == pre_cutoff_decision_id
    assert active_decisions[0]["state"] == "substantiated"

    # -------------------------------------------------------------------------
    # 22. Verify unauthorized cross-entity report access is rejected (403 Forbidden)
    # -------------------------------------------------------------------------
    other_entity_id = "CSE-FINTECH-02"
    other_user = User(
        id="usr-other-entity-01",
        username="other_examiner",
        password_hash=hash_password("OtherPass123!"),
        role="examiner",
        entity_scope=json.dumps([other_entity_id]),
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()

    other_login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "other_examiner", "password": "OtherPass123!"},
    )
    assert other_login_resp.status_code == 200
    other_csrf = other_login_resp.json()["csrf_token"]
    other_headers = {"X-CSRF-Token": other_csrf}

    # Attempt to read bank report as fintech examiner -> 403 Forbidden
    cross_read_resp = client.get(f"/api/v1/reports/{report_id}", headers=other_headers)
    assert cross_read_resp.status_code == 403
    cross_dl_resp = client.get(f"/api/v1/reports/{report_id}/html", headers=other_headers)
    assert cross_dl_resp.status_code == 403
