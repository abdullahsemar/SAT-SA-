"""Migration-backed acceptance workflow test for SAT-SA.

Creates a NEW temporary database using Alembic migrations (alembic upgrade head),
then exercises the entire supervisory lifecycle:
1. Actual login and cookie/CSRF token behavior.
2. Manifest creation and file-byte upload for all operational sources.
3. Validation, commitment, and assessment analysis run.
4. Finding inspection, source-record inspection, case and asset evidence chains.
5. Persisted similarity retrieval without recomputation.
6. Saved portfolio generation and reopening with stable order.
7. Finding-level human determination.
8. Unflagged review-item decision without creating a machine finding.
9. Evidence request against an item with no finding.
10. Report creation and HTML/JSON/manifest/ZIP retrieval.
11. Checksum and ZIP-content verification.
12. Later human decision, followed by byte-for-byte verification that the earlier report is unchanged.
13. Entity isolation throughout.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.auth import hash_password
from apps.api.config import settings
from apps.api.main import app
from db.models.access import User
from db.models.evidence import CSE
from db.session import get_db
from packages.reporting.manifest import ChecksumManifest


def test_migration_backed_acceptance_workflow(tmp_path: Path):
    # -------------------------------------------------------------------------
    # 0. Setup a NEW temporary SQLite database using Alembic migrations
    # -------------------------------------------------------------------------
    db_file = tmp_path / "acceptance.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    orig_storage = settings.storage_dir
    orig_db_url = os.environ.get("DATABASE_URL")
    settings.storage_dir = str(storage_dir)
    os.environ["DATABASE_URL"] = db_url

    # Run Alembic migrations against the fresh file
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    # Connect to the migrated database
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    MigratedSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = MigratedSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with MigratedSession() as init_db:
            # Seed Entities
            cse_bank = "CSE-BANK-01"
            cse_fintech = "CSE-FINTECH-02"
            init_db.add(CSE(id=cse_bank, code=cse_bank, name="First National Bank CSE"))
            init_db.add(CSE(id=cse_fintech, code=cse_fintech, name="Fintech Payments CSE"))

            # Seed Users
            bank_examiner_user = User(
                id="usr-bank-lead-01",
                username="lead_bank_examiner",
                password_hash=hash_password("BankExaminerPass123!"),
                role="examiner",
                entity_scope=json.dumps([cse_bank]),
                is_active=True,
            )
            fintech_examiner_user = User(
                id="usr-fintech-lead-01",
                username="lead_fintech_examiner",
                password_hash=hash_password("FintechExaminerPass123!"),
                role="examiner",
                entity_scope=json.dumps([cse_fintech]),
                is_active=True,
            )
            init_db.add_all([bank_examiner_user, fintech_examiner_user])
            init_db.commit()

        with TestClient(app) as client:
            # ---------------------------------------------------------------------
            # 1. Actual login and cookie/CSRF token behavior
            # ---------------------------------------------------------------------
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"username": "lead_bank_examiner", "password": "BankExaminerPass123!"},
            )
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            profile = login_resp.json()
            assert profile["username"] == "lead_bank_examiner"
            assert cse_bank in profile["entity_scope"]
            csrf_token = profile.get("csrf_token")
            assert csrf_token is not None

            bank_headers = {"X-CSRF-Token": csrf_token}

            # ---------------------------------------------------------------------
            # 2. Manifest creation and file-byte upload for all operational sources
            # ---------------------------------------------------------------------
            manifest_payload = {
                "manifest_version": "1.0.0",
                "entity_id": cse_bank,
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

            sub_resp = client.post(
                "/api/v1/submissions", json=manifest_payload, headers=bank_headers
            )
            assert sub_resp.status_code == 201
            sub_data = sub_resp.json()
            submission_id = sub_data["id"]
            assert sub_data["status"] == "draft"

            # Upload real payload bytes
            cases_data = [
                {
                    "native_id": "CASE-MIG-01",
                    "case_id": "CASE-MIG-01",
                    "severity": "CRITICAL",
                    "status": "CLOSED",
                    "created_at": "2026-08-05T10:00:00Z",
                    "closed_at": "2026-08-05T10:30:00Z",
                    "root_cause": "Malware isolated",
                    "resolution": "RESOLVED",
                },
                {
                    "native_id": "CASE-MIG-02",
                    "case_id": "CASE-MIG-02",
                    "severity": "CRITICAL",
                    "status": "CLOSED",
                    "created_at": "2026-08-10T14:00:00Z",
                    "closed_at": "2026-08-11T18:00:00Z",
                    "root_cause": "Ransomware perimeter breach",
                    "resolution": "CONTAINED",
                },
                {
                    "native_id": "CASE-MIG-03",
                    "case_id": "CASE-MIG-03",
                    "severity": "MEDIUM",
                    "status": "CLOSED",
                    "created_at": "2026-08-12T09:00:00Z",
                    "closed_at": "2026-08-12T09:30:00Z",
                    "resolution": "FALSE_POSITIVE",
                },
            ]
            actions_data = [
                {
                    "native_id": "ACT-MIG-01",
                    "action_id": "ACT-MIG-01",
                    "case_id": "CASE-MIG-01",
                    "action_type": "HOST_ISOLATION",
                    "actor": "secops-t2",
                    "timestamp": "2026-08-05T10:10:00Z",
                },
                {
                    "native_id": "ACT-MIG-02",
                    "action_id": "ACT-MIG-02",
                    "case_id": "CASE-MIG-01",
                    "action_type": "FORENSIC_TRIAGE",
                    "actor": "secops-t2",
                    "timestamp": "2026-08-05T10:15:00Z",
                },
                {
                    "native_id": "ACT-MIG-03",
                    "action_id": "ACT-MIG-03",
                    "case_id": "CASE-MIG-02",
                    "action_type": "FORENSIC_TRIAGE",
                    "actor": "secops-t1",
                    "timestamp": "2026-08-10T15:00:00Z",
                },
            ]
            escalations_data = [
                {
                    "native_id": "ESC-MIG-01",
                    "escalation_id": "ESC-MIG-01",
                    "case_id": "CASE-MIG-01",
                    "escalation_type": "PAGERDUTY",
                    "escalation_level": "TIER_3",
                    "notified_party": "oncall-lead@bank.internal",
                    "timestamp": "2026-08-05T10:05:00Z",
                }
            ]
            assets_data = [
                {
                    "native_id": "AST-MIG-01",
                    "asset_id": "AST-MIG-01",
                    "hostname": "core01.bank.internal",
                    "criticality": "CRITICAL",
                    "agent_status": "HEALTHY",
                    "last_heartbeat": "2026-08-31T23:50:00Z",
                },
                {
                    "native_id": "AST-MIG-02",
                    "asset_id": "AST-MIG-02",
                    "hostname": "app02.bank.internal",
                    "criticality": "HIGH",
                    "agent_status": "HEALTHY",
                    "last_heartbeat": "2026-08-31T23:45:00Z",
                },
            ]
            claims_data = [
                {
                    "native_id": "CLM-MIG-01",
                    "claim_id": "CLM-MIG-01",
                    "metric_name": "incident_sla_compliance_pct",
                    "period": "2026-08",
                    "metric_value": 99.0,
                }
            ]

            uploads = [
                ("src-cases", "cases.json", json.dumps(cases_data).encode()),
                ("src-actions", "actions.json", json.dumps(actions_data).encode()),
                ("src-esc", "escalations.json", json.dumps(escalations_data).encode()),
                ("src-assets", "assets.json", json.dumps(assets_data).encode()),
                ("src-claims", "claims.json", json.dumps(claims_data).encode()),
            ]

            for src_id, filename, file_bytes in uploads:
                up_resp = client.post(
                    f"/api/v1/submissions/{submission_id}/files",
                    data={"source_id": src_id},
                    files={"file": (filename, file_bytes, "application/json")},
                    headers=bank_headers,
                )
                assert up_resp.status_code in (200, 201)

            # ---------------------------------------------------------------------
            # 3. Validation, commitment, and assessment analysis run
            # ---------------------------------------------------------------------
            val_resp = client.post(
                f"/api/v1/submissions/{submission_id}/validate", headers=bank_headers
            )
            assert val_resp.status_code == 200
            val_data = val_resp.json()
            assert val_data["status"] == "validated"

            # Verify draft protection before commit
            draft_run_resp = client.post(
                "/api/v1/analysis-runs",
                json={"submission_id": submission_id, "semantic_mode": "off"},
                headers=bank_headers,
            )
            assert draft_run_resp.status_code == 409

            commit_resp = client.post(
                f"/api/v1/submissions/{submission_id}/commit", headers=bank_headers
            )
            assert commit_resp.status_code == 200
            assert commit_resp.json()["status"] == "committed"

            # Post-commit mutation protection
            post_up_resp = client.post(
                f"/api/v1/submissions/{submission_id}/files",
                data={"source_id": "src-cases"},
                files={"file": ("more.json", b"[]", "application/json")},
                headers=bank_headers,
            )
            assert post_up_resp.status_code == 409

            # Run Assessment
            run_resp = client.post(
                "/api/v1/analysis-runs",
                json={"submission_id": submission_id, "semantic_mode": "off"},
                headers=bank_headers,
            )
            assert run_resp.status_code == 201
            run_data = run_resp.json()
            run_id = run_data["run_id"]
            assert run_data["status"] == "completed"

            # ---------------------------------------------------------------------
            # 4. Finding inspection, source-record inspection, evidence chains
            # ---------------------------------------------------------------------
            findings_resp = client.get(f"/api/v1/findings?run_id={run_id}", headers=bank_headers)
            assert findings_resp.status_code == 200
            findings = findings_resp.json()
            assert len(findings) >= 2

            # Escalation overdue finding on CASE-MIG-02
            esc_findings = [
                f
                for f in findings
                if f["rule_id"] == "POL-ESC-002" and f["primary_object_id"] == "CASE-MIG-02"
            ]
            assert len(esc_findings) == 1
            esc_finding = esc_findings[0]
            assert esc_finding["evidence_state"] == "potential_concern"

            # Inspect source record
            rec_resp = client.get("/api/v1/evidence/records/CASE-MIG-01", headers=bank_headers)
            assert rec_resp.status_code == 200
            rec_data = rec_resp.json()
            assert rec_data["native_id"] == "CASE-MIG-01"
            assert rec_data["entity_id"] == cse_bank

            # Inspect case evidence chain
            chain_resp = client.get(
                f"/api/v1/evidence/chains/CASE-MIG-01?submission_id={submission_id}",
                headers=bank_headers,
            )
            assert chain_resp.status_code == 200
            chain_data = chain_resp.json()
            assert chain_data["object_id"] == "CASE-MIG-01"

            # ---------------------------------------------------------------------
            # 5. Persisted similarity retrieval without recomputation
            # ---------------------------------------------------------------------
            sem_resp = client.get(
                f"/api/v1/findings/{esc_finding['finding_id']}/similar-passages",
                headers=bank_headers,
            )
            assert sem_resp.status_code == 200
            sem_data = sem_resp.json()
            assert sem_data["finding_id"] == esc_finding["finding_id"]
            assert sem_data["status"] in ("completed", "disabled", "not_computed")

            # ---------------------------------------------------------------------
            # 6. Saved portfolio generation and reopening with stable order
            # ---------------------------------------------------------------------
            port_resp = client.post(
                "/api/v1/review-portfolios",
                json={
                    "run_id": run_id,
                    "max_items": 5,
                    "strata_allocation": {"targeted": 2, "control": 1, "exploratory": 1},
                    "seed": 42,
                },
                headers=bank_headers,
            )
            assert port_resp.status_code == 201
            portfolio_data = port_resp.json()
            portfolio_id = portfolio_data["id"]
            items = portfolio_data["items"]
            assert len(items) > 0

            # Reopen portfolio and verify identical stable order
            reopen_resp = client.get(
                f"/api/v1/review-portfolios/{portfolio_id}", headers=bank_headers
            )
            assert reopen_resp.status_code == 200
            reopened_items = reopen_resp.json()["items"]
            assert [it["id"] for it in items] == [it["id"] for it in reopened_items]
            assert [it["marginal_reasons"] for it in items] == [
                it["marginal_reasons"] for it in reopened_items
            ]

            # ---------------------------------------------------------------------
            # 7. Finding-level human determination
            # ---------------------------------------------------------------------
            f_dec_resp = client.post(
                f"/api/v1/findings/{esc_finding['finding_id']}/decisions",
                json={
                    "state": "substantiated",
                    "rationale": "Examiner substantiated overdue escalation SLA breach.",
                    "cited_evidence_ids": [],
                },
                headers=bank_headers,
            )
            assert f_dec_resp.status_code == 201
            f_dec_data = f_dec_resp.json()
            assert f_dec_data["state"] == "substantiated"
            pre_cutoff_dec_id = f_dec_data["id"]

            # ---------------------------------------------------------------------
            # 8. Unflagged review-item decision without creating a machine finding
            # ---------------------------------------------------------------------
            ctrl_items = [it for it in items if it["stratum"] == "control"]
            assert len(ctrl_items) >= 1
            ctrl_item = ctrl_items[0]
            assert ctrl_item["finding_id"] is None

            item_dec_resp = client.post(
                f"/api/v1/review-items/{ctrl_item['id']}/decisions",
                json={
                    "state": "reviewed_no_concern",
                    "rationale": "Control case reviewed; compliant without deficiency.",
                    "cited_evidence_ids": [],
                },
                headers=bank_headers,
            )
            assert item_dec_resp.status_code == 201
            assert item_dec_resp.json()["state"] == "reviewed_no_concern"

            # Verify no machine finding was created
            findings_after = client.get(
                f"/api/v1/findings?run_id={run_id}", headers=bank_headers
            ).json()
            assert len(findings_after) == len(findings)

            # ---------------------------------------------------------------------
            # 9. Evidence request against an item with no finding
            # ---------------------------------------------------------------------
            ev_req_resp = client.post(
                "/api/v1/evidence-requests",
                json={
                    "review_item_id": ctrl_item["id"],
                    "missing_artifact": "analyst_shift_handover_log.pdf",
                    "distinguishing_question": "Does shift handover note confirm resolution before shift end?",
                    "responsible_owner": "SOC Tier 1 Lead",
                    "due_date": "2026-09-30T17:00:00Z",
                },
                headers=bank_headers,
            )
            assert ev_req_resp.status_code == 201
            assert ev_req_resp.json()["review_item_id"] == ctrl_item["id"]
            assert ev_req_resp.json()["status"] == "open"

            # ---------------------------------------------------------------------
            # 10. Report creation and HTML/JSON/manifest/ZIP retrieval
            # ---------------------------------------------------------------------
            t_cutoff = datetime.now(timezone.utc)
            rep_resp = client.post(
                "/api/v1/reports",
                json={
                    "run_id": run_id,
                    "portfolio_id": portfolio_id,
                    "decision_cutoff_time": t_cutoff.isoformat(),
                    "notes": "Migration acceptance test report.",
                },
                headers=bank_headers,
            )
            assert rep_resp.status_code == 201
            report_id = rep_resp.json()["id"]

            # JSON Snapshot
            r_json = client.get(f"/api/v1/reports/{report_id}/json", headers=bank_headers)
            assert r_json.status_code == 200
            snapshot_bytes = r_json.content

            # HTML
            r_html = client.get(f"/api/v1/reports/{report_id}/html", headers=bank_headers)
            assert r_html.status_code == 200
            html_bytes = r_html.content

            # Manifest
            r_man = client.get(f"/api/v1/reports/{report_id}/manifest", headers=bank_headers)
            assert r_man.status_code == 200
            man_data = r_man.json()

            # ---------------------------------------------------------------------
            # 11. Checksum and ZIP-content verification
            # ---------------------------------------------------------------------
            assert ChecksumManifest.verify_artifact(
                snapshot_bytes, man_data["components"]["snapshot_json"]["sha256"]
            )
            assert ChecksumManifest.verify_artifact(
                html_bytes, man_data["components"]["assessment_html"]["sha256"]
            )

            r_zip = client.get(f"/api/v1/reports/{report_id}/bundle", headers=bank_headers)
            assert r_zip.status_code == 200
            with zipfile.ZipFile(io.BytesIO(r_zip.content)) as zf:
                assert zf.read("assessment.html") == html_bytes
                assert zf.read("snapshot.json") == snapshot_bytes

            # ---------------------------------------------------------------------
            # 12. Later human decision, verify earlier report is byte-for-byte unchanged
            # ---------------------------------------------------------------------
            late_dec_resp = client.post(
                f"/api/v1/findings/{esc_finding['finding_id']}/decisions",
                json={
                    "state": "not_applicable",
                    "rationale": "Closed in post-audit review.",
                    "cited_evidence_ids": [],
                    "expected_version": 2,
                },
                headers=bank_headers,
            )
            assert late_dec_resp.status_code == 201

            # Re-fetch report json and verify identical byte content
            recheck_json = client.get(f"/api/v1/reports/{report_id}/json", headers=bank_headers)
            assert recheck_json.status_code == 200
            assert recheck_json.content == snapshot_bytes
            recheck_data = recheck_json.json()
            active_decs = [
                d for d in recheck_data["examiner_decisions"]["finding_decisions"] if d["is_active"]
            ]
            assert len(active_decs) == 1
            assert active_decs[0]["decision_id"] == pre_cutoff_dec_id

            # ---------------------------------------------------------------------
            # 13. Entity isolation throughout
            # ---------------------------------------------------------------------
            fintech_login_resp = client.post(
                "/api/v1/auth/login",
                json={"username": "lead_fintech_examiner", "password": "FintechExaminerPass123!"},
            )
            assert fintech_login_resp.status_code == 200
            fintech_headers = {"X-CSRF-Token": fintech_login_resp.json()["csrf_token"]}

            # Fintech examiner accessing bank submission -> 403
            assert (
                client.get(
                    f"/api/v1/submissions/{submission_id}", headers=fintech_headers
                ).status_code
                == 403
            )
            # Fintech examiner accessing specific bank finding -> 403
            assert (
                client.get(
                    f"/api/v1/findings/{esc_finding['finding_id']}", headers=fintech_headers
                ).status_code
                == 403
            )
            # Fintech examiner listing findings for bank run -> filtered out (0 returned)
            foreign_findings = client.get(
                f"/api/v1/findings?run_id={run_id}", headers=fintech_headers
            ).json()
            assert len(foreign_findings) == 0
            # Fintech examiner accessing bank report -> 403
            assert (
                client.get(f"/api/v1/reports/{report_id}", headers=fintech_headers).status_code
                == 403
            )

    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        settings.storage_dir = orig_storage
        if orig_db_url:
            os.environ["DATABASE_URL"] = orig_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        shutil.rmtree(storage_dir, ignore_errors=True)
